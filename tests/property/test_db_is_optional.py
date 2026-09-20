"""Phase 13 gate 2 — the database is OPTIONAL, and that is not a degraded mode.

`python -m shipdoc` with no `DATABASE_URL` must behave exactly as it did before
Phase 13 existed: same submission, same hash, no error, no warning that looks like
one. The clean-clone gate depends on it, and so does anyone evaluating this system
on a laptop.

The strongest version of this claim is not "it does not crash" but "the bytes are
identical", so that is what is asserted.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT


def test_no_database_url_means_no_repository(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from shipdoc.adapters.db import build_repository, database_url
    assert database_url() is None
    assert build_repository() is None


def test_an_empty_database_url_is_treated_as_unset(monkeypatch):
    """A blank env var is how this breaks in a container: the variable is declared
    in the compose file with no value, and a naive `if "DATABASE_URL" in os.environ`
    tries to connect to the empty string."""
    from shipdoc.adapters.db import build_repository
    for blank in ("", "   "):
        monkeypatch.setenv("DATABASE_URL", blank)
        assert build_repository() is None


def test_save_run_to_db_is_a_no_op_without_a_database(monkeypatch, tmp_path):
    """The call site must not need to know whether a database exists."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from shipdoc.pipeline import save_run_to_db

    from shipdoc.config import load_config
    cfg = load_config(ROOT / "config")
    # No exception, no side effect, no output file required.
    save_run_to_db({"summary": {}, "submission": {}, "records": []},
                   cfg, str(ROOT / "config"), tmp_path)


def test_the_db_cli_reports_absence_as_normal_not_as_an_error(monkeypatch, capsys):
    """Exit 0. A non-zero exit here would fail a CI pipeline for a supported mode."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from shipdoc import db_cli
    assert db_cli.run("check") == 0
    out = capsys.readouterr().out
    assert "supported mode, not an error" in out


@pytest.mark.slow
def test_a_run_with_no_database_reproduces_the_committed_hash(tmp_path):
    """GATE 2, end to end, in a subprocess with DATABASE_URL removed.

    A subprocess rather than an in-process call because the thing under test is the
    behaviour of the actual command a person types, including its imports.
    """
    expected = _committed_hash()
    if expected is None:
        pytest.skip("no published hash recorded in HANDOVER.md")

    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, "-m", "shipdoc", "--quiet", "--out", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=1800)
    assert proc.returncode == 0, proc.stderr[-2000:]

    sub = out / "submission.json"
    assert sub.is_file(), "the run must have WRITTEN the file, not just exited 0"

    import hashlib
    got = hashlib.sha256(sub.read_bytes()).hexdigest()
    assert got == expected, (
        f"a run with no database produced {got}, not the published {expected}")


def _committed_hash() -> str | None:
    """Read the published hash out of HANDOVER.md rather than hard-coding it here.

    A hash pasted into a test is a hash that silently goes stale; reading it from the
    document that publishes it means the two can never disagree.
    """
    import re
    text = (ROOT / "HANDOVER.md").read_text(encoding="utf-8")
    m = re.search(r"learned vocabulary PRESENT\s+submission\.json\s+([0-9a-f]{64})",
                  text)
    if m:
        return m.group(1)
    m = re.search(r"submission\.json\s+([0-9a-f]{64})", text)
    return m.group(1) if m else None
