"""What this machine can actually do.

Every optional dependency is probed here and nowhere else, so a missing one is a
DEGRADED MODE with a message rather than an ImportError three layers down. Importing
`shipdoc` with none of the optional pieces installed must succeed — that is the
contract this module exists to keep.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

OLLAMA_URL = "http://localhost:11434"
SCOREBOARD_URL = "http://localhost:8080"

# NOTE: there is deliberately no answer-key probe here. The answer key is a measuring
# instrument, and the package must not know where it lives — not even to report that
# it exists. `eval/evaluate.py` owns that path and says so plainly if it is missing.
# tests/property/test_no_answer_key_leak.py enforces this.


@dataclass(frozen=True)
class Capability:
    name: str
    ok: bool
    detail: str
    remedy: str = ""
    optional: bool = True


def _module_present(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def have_pdf() -> bool:
    return _module_present("fitz")


def have_xlsx() -> bool:
    return _module_present("openpyxl")


def have_docx() -> bool:
    return _module_present("docx")


def have_ocr() -> bool:
    """Both halves: the Python binding AND the tesseract binary."""
    return (_module_present("pytesseract") and _module_present("PIL")
            and shutil.which("tesseract") is not None)


def tesseract_path() -> str | None:
    return shutil.which("tesseract")


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ollama_models(timeout: float = 2.0) -> list[str] | None:
    """Model names, or None when no server answers."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as r:
            return [m["name"] for m in json.load(r).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def have_llm(timeout: float = 2.0) -> bool:
    return ollama_models(timeout) is not None


def have_scoreboard(timeout: float = 2.0) -> bool:
    return _http_ok(f"{SCOREBOARD_URL}/health", timeout)


def probe(cfg=None, root: Path | None = None, *,
          check_network: bool = True) -> list[Capability]:
    """The full picture, in banner order. Cheap except for two 2s HTTP timeouts."""
    root = root or Path.cwd()
    caps: list[Capability] = []

    dataset = root / "dataset"
    n_inbox = len(list((dataset / "inbox").glob("email_*.json"))) if dataset.is_dir() else 0
    n_att = len(list((dataset / "attachments").iterdir())) if (dataset / "attachments").is_dir() else 0
    caps.append(Capability(
        "corpus", n_inbox > 0, f"{n_inbox} emails, {n_att} attachments",
        remedy="dataset/ not found — run from the repo root, or pass --source",
        optional=False))

    caps.append(Capability("rule extraction", True, "text + rules, always available",
                           optional=False))

    caps.append(Capability(
        "PDF extraction", have_pdf(), "pymupdf" if have_pdf() else "pymupdf not installed",
        remedy='pip install -e "."   (pymupdf is a core dependency)'))
    caps.append(Capability(
        "Excel extraction", have_xlsx(),
        "openpyxl" if have_xlsx() else "openpyxl not installed",
        remedy='pip install -e "."'))
    caps.append(Capability(
        "Word extraction", have_docx(),
        "python-docx" if have_docx() else "python-docx not installed",
        remedy='pip install -e "."'))

    tp = tesseract_path()
    caps.append(Capability(
        "OCR", have_ocr(),
        f"tesseract at {tp}" if have_ocr() else "tesseract not found — scans -> NEEDS_REVIEW",
        remedy='winget install UB-Mannheim.TesseractOCR   then  pip install -e ".[ocr]"'))

    if check_network:
        models = ollama_models()
        caps.append(Capability(
            "LLM", models is not None,
            f"{len(models)} model(s) at {OLLAMA_URL}" if models
            else f"no server at {OLLAMA_URL} — rules-only classification",
            remedy="install Ollama, then: ollama pull qwen2.5:7b-instruct"))
        caps.append(Capability(
            "scoring server", have_scoreboard(),
            f"reachable at {SCOREBOARD_URL}" if have_scoreboard()
            else "not reachable — omit --submit",
            remedy="cd ../sdoc-server && docker compose up -d"))
    if cfg is not None:
        on = getattr(cfg.flags, "port_resolution_enabled", False)
        caps.append(Capability(
            "port resolution", on,
            "enabled" if on else "disabled (Phase 5, flag off — see BACKUP notes)",
            remedy="config/pipeline.yaml -> flags.port_resolution_enabled: true"))

    return caps


def banner(caps: list[Capability], version: str = "") -> str:
    lines = [f"shipdoc {version} — capability check".rstrip()]
    for c in caps:
        mark = "ok" if c.ok else ("--" if c.optional else "FAIL")
        lines.append(f"  [{mark:<4}] {c.name:<18} {c.detail}")
    return "\n".join(lines)
