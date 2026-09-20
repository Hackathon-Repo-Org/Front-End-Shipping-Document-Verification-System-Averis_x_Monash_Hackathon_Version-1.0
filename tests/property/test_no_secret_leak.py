"""Phase 12 A2 — no API key may exist anywhere in the published artefacts.

This repository is PUBLIC. A key committed here is a key revoked by an automated
scanner within minutes if you are lucky, and billed to someone else if you are not.

The scan is deliberately broader than "did we commit a key": it covers the source
tree, the committed LLM cache, the config, the docs and the run artifacts, because a
key leaks through the boring paths — an error message echoed into a StageEvent, a
`repr()` in a traceback, a debug print left in a cache value.

`.env` is gitignored and `.env.example` carries placeholders only; both are asserted
below rather than assumed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from conftest import ROOT

# Shapes of real keys across the providers this system can speak to. The point is to
# catch a key that got where it should not be, so match the SHAPE, not one vendor.
#   sk-…            OpenAI, DeepSeek
#   gsk_…           Groq
#   AccountKey=…    an Azure storage connection string
KEY_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxai-[A-Za-z0-9]{20,}\b"),
    re.compile(r"AccountKey=[A-Za-z0-9+/]{40,}={0,2}"),
    re.compile(r"\bghp_[A-Za-z0-9]{30,}\b"),          # GitHub, learned the hard way
    re.compile(r"postgres(?:ql)?://[^\s:@/]+:[^\s@/]{3,}@"),   # password in a URL
)

# Placeholders that are SUPPOSED to look key-shaped. Anything else matching a shape
# is a finding.
ALLOWED = ("sk-replace-me", "gsk_replace-me", "sk-your-key-here",
           "user:password@host")

SCAN_DIRS = ("src", "config", "cache", "tests", "docs", "eval", "alembic")
SCAN_FILES = (".env.example", "README.md", "SETUP.md", "TESTING.md", "HANDOVER.md",
              "pyproject.toml")

TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".json", ".md", ".txt", ".toml", ".cfg",
                 ".ini", ".sql", ".example", ""}


def fake_key(prefix: str = "sk-") -> str:
    """Build a key-shaped string at RUNTIME.

    The obvious way to write these tests is to paste a fake key literal — at which
    point this file trips its own scanner, and the tempting fix is an allowlist
    entry. An allowlist entry for a key-shaped string is a hole a real key can hide
    in. Assembling it from parts keeps the scanner strict and the fixtures honest.
    """
    import string
    return prefix + string.ascii_lowercase + string.digits[:6]


def _candidate_files():
    for d in SCAN_DIRS:
        root = ROOT / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts \
                    and p.suffix.lower() in TEXT_SUFFIXES:
                yield p
    for name in SCAN_FILES:
        p = ROOT / name
        if p.is_file():
            yield p


def _findings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    hits = []
    for pat in KEY_SHAPES:
        for m in pat.finditer(text):
            if any(a in m.group(0) for a in ALLOWED):
                continue
            hits.append(f"{path.relative_to(ROOT)}: {pat.pattern} -> {m.group(0)[:16]}…")
    return hits


def test_no_key_shaped_string_anywhere_in_the_tree():
    """The whole published tree, including the committed LLM cache."""
    findings = [f for p in _candidate_files() for f in _findings(p)]
    assert not findings, "possible secret(s) committed:\n  " + "\n  ".join(findings)


def test_the_committed_cache_contains_no_secrets():
    """Called out separately because the cache is machine-written.

    Nobody reviews 431 hash-named files by eye, so the only thing standing between a
    leaked key and a public repo is this assertion.
    """
    cache = ROOT / "cache"
    if not cache.is_dir():
        pytest.skip("no committed cache")
    findings = []
    for p in cache.rglob("*"):
        if p.is_file():
            findings.extend(_findings(p))
    assert not findings, "secret(s) in the committed cache:\n  " + "\n  ".join(findings)


def test_dotenv_is_ignored_and_the_example_is_not():
    """A .env.example that is itself ignored teaches nobody anything, and a .env that
    is NOT ignored is one `git add -A` from a public key."""
    assert (ROOT / ".env.example").is_file(), ".env.example must be committed"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^\.env$", gitignore, re.MULTILINE), ".env must be gitignored"
    assert "!.env.example" in gitignore, ".env.example must be re-included"


def test_dotenv_example_holds_placeholders_only():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert not _findings(ROOT / ".env.example"), "a real key is in .env.example"
    assert "DEEPSEEK_API_KEY" in example


def test_git_tracks_no_dotenv():
    """Belt and braces: ask git what it is actually tracking."""
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        pytest.skip("git not available")
    tracked = {line.strip() for line in out.splitlines()}
    assert ".env" not in tracked
    assert not any(t.startswith(".env.") and t != ".env.example" for t in tracked)


def test_the_hosted_client_never_reprs_its_key():
    """The default repr of an object holding a secret is how secrets reach logs."""
    from shipdoc.llm.hosted import HostedClient

    pytest.importorskip("openai")
    key = fake_key()
    c = HostedClient("deepseek-chat", provider="deepseek", api_key=key)
    for rendered in (repr(c), str(c), f"{c}"):
        assert key not in rendered and key[3:13] not in rendered
        assert "<redacted>" in rendered


def test_error_messages_are_scrubbed_of_keys():
    """Providers sometimes echo the Authorization header back in an error body, and
    that text ends up in a StageEvent, the review queue and the database."""
    from shipdoc.llm.hosted import _safe_message

    key = fake_key()
    msg = _safe_message(RuntimeError(f"401 unauthorized: Authorization: Bearer {key}"))
    assert key not in msg and key[3:13] not in msg
    assert "redacted" in msg


def test_missing_key_degrades_cleanly_without_a_traceback():
    """A2: missing key is a readable message and rules-only classification, never a
    crash and never a stack trace echoing config."""
    import os

    from shipdoc.llm.hosted import HostedClient, MissingAPIKey

    saved = os.environ.pop("DEEPSEEK_API_KEY", None)
    try:
        with pytest.raises(MissingAPIKey) as e:
            HostedClient("deepseek-chat", provider="deepseek")
    finally:
        if saved is not None:
            os.environ["DEEPSEEK_API_KEY"] = saved
    msg = str(e.value)
    assert "DEEPSEEK_API_KEY is not set" in msg
    assert "llm.provider: ollama" in msg, "must name the offline escape hatch"
    assert "keyword rules" in msg, "must say what happens instead"
