"""Run artifacts must be byte-identical on every platform.

WHY THIS IS A TEST AND NOT A COMMENT
------------------------------------
Python's text mode translates "\\n" to the platform line separator. Every artifact
this project published was written on Windows and therefore carried CRLF; Azure
Container Apps runs Linux and would have written LF. Same content, different bytes,
different sha256 — and the first person to notice would have been a judge comparing
the deployed service's output against the published hash.

The content was never platform-dependent. Only the line endings were. `write_atomic`
now pins `newline="\\n"`, and this file is what stops the pin quietly coming out
during a future refactor. An invariant with no guard is a convention, and conventions
do not survive.

The published hashes changed exactly once, when this was fixed. Both the old and the
new are recorded in HANDOVER.md so that older reports remain interpretable.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import ROOT
from shipdoc.pipeline import write_atomic

PAYLOAD = {
    "email_001": {"status": "OK", "defect_fields": [], "has_defect": False},
    "email_002": {"status": "MISMATCH", "defect_fields": ["shipper"],
                  "has_defect": True, "review_reason": None},
    # Non-ASCII, because ensure_ascii=False means these reach the file as UTF-8 and
    # an encoding change would be just as invisible as a newline change.
    "email_003": {"status": "NEEDS_REVIEW", "note": "Gross Weight毛重(KGS)"},
}


def test_written_artifacts_contain_no_carriage_return(tmp_path):
    """THE cross-platform invariant. A single \\r makes the hash platform-dependent."""
    p = tmp_path / "submission.json"
    write_atomic(p, PAYLOAD)
    data = p.read_bytes()
    assert b"\r" not in data, (
        "a CR byte reached a run artifact: write_atomic must pin newline='\\n', "
        "or Windows and Linux will publish different hashes for identical content")
    assert data.endswith(b"\n"), "artifacts end with exactly one newline"


def test_the_hash_does_not_depend_on_the_platform(tmp_path):
    """Compare against bytes assembled explicitly, with no OS involvement."""
    import hashlib

    p = tmp_path / "a.json"
    write_atomic(p, PAYLOAD)
    expected = (json.dumps(PAYLOAD, indent=2, sort_keys=False, ensure_ascii=False)
                + "\n").encode("utf-8")
    assert p.read_bytes() == expected
    assert hashlib.sha256(p.read_bytes()).hexdigest() == \
           hashlib.sha256(expected).hexdigest()


def test_utf8_survives_the_round_trip(tmp_path):
    p = tmp_path / "a.json"
    write_atomic(p, PAYLOAD)
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back == PAYLOAD
    assert "毛重" in p.read_text(encoding="utf-8"), \
        "ensure_ascii=False must keep the CJK gloss as real UTF-8"


def test_writing_twice_produces_identical_bytes(tmp_path):
    """I6, at the file level."""
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write_atomic(a, PAYLOAD)
    write_atomic(b, PAYLOAD)
    assert a.read_bytes() == b.read_bytes()


@pytest.mark.parametrize("name", ["submission.json", "run_summary.json"])
def test_the_committed_artifacts_on_disk_are_lf_only(name):
    """Not just what we write now — what is actually sitting in output/ today.

    A stale CRLF artifact left over from before the fix would make a gate pass
    against the wrong bytes.
    """
    p = ROOT / "output" / name
    if not p.is_file():
        pytest.skip(f"{name} not present; run `python -m shipdoc` first")
    assert b"\r" not in p.read_bytes(), f"output/{name} still has CRLF line endings"
