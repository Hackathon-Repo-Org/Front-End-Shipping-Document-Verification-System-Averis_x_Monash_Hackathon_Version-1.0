"""M17d — `Record` objects to database rows. Phase 13.

This is the ONLY place that knows both shapes. Keeping it here rather than on the
`Record` type is what stops the database leaking downward into the core: `types.py`
must not grow a `to_row()` method, because then every module that touches a Record
transitively depends on the schema.

The projection reuses `SubmissionAdapter` for the external fields (status,
review_reason, has_defect) rather than recomputing them. Two implementations of
"what does this record mean" is exactly how a dashboard ends up disagreeing with the
submission it was built from.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from decimal import Decimal, InvalidOperation
from pathlib import Path


def code_version(repo_root: Path | None = None) -> str:
    """The git sha, or a readable marker when git is unavailable.

    R4 wants to know what code produced a run. 'unknown' is a worse answer than a
    sha, but it is an honest one; inventing a version number is not.
    """
    root = repo_root or Path.cwd()
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=15)
        sha = out.stdout.strip()
        if out.returncode == 0 and sha:
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                   capture_output=True, text=True, timeout=20)
            return sha + ("-dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def sha256_json(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def config_sha256(config_dir: Path) -> str:
    """Hash of every config file, so a threshold change is visible in `runs`."""
    h = hashlib.sha256()
    for p in sorted(Path(config_dir).glob("*.yaml")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _numeric(value) -> Decimal | None:
    """NUMERIC, never float. Returns None for anything that is not a clean number."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _evidence(fv) -> dict | None:
    """{file, line, cell, page, method} — what a reviewer needs to find the value.

    `locator` is stored as given ('line 21', 'B7') rather than parsed into an int,
    because a spreadsheet cell is not a line number and forcing both into one column
    loses whichever one you did not think about.
    """
    if fv is None:
        return None
    src = getattr(fv, "source", None)
    ev = {
        "file": getattr(src, "file", None),
        "locator": getattr(src, "locator", None),
        "method": getattr(getattr(fv, "method", None), "value", None),
        "label_seen": getattr(fv, "label_seen", None),
    }
    # Phase 10 Fix 2: a substituted value must never look like a read one.
    if getattr(fv, "resolved_from", None):
        ev["resolved_from"] = fv.resolved_from
        ev["reference_text"] = fv.reference_text
    return ev


def record_rows(records, submission: dict) -> list[dict]:
    """One dict per record, ready for `SQLRepository.save_run`.

    `decided_by` ('rule' | 'llm') is read from `Record.decided_by`, which the arbiter
    sets at the moment it decides. The dashboard reports the AI's share of decisions
    from this column, so it must reflect what actually happened on that record — not
    which provider was configured, and not a guess from the confidence number.
    """
    rows = []
    for rec in records:
        sub = submission.get(rec.email_id, {})
        rows.append({
            "email_id": rec.email_id,
            "category": rec.category,
            "decided_by": _decided_by(rec),
            "state": rec.state.value if rec.state is not None else "failed",
            "reason_key": rec.reason.value if rec.reason is not None else None,
            "status": sub.get("status", "NEEDS_REVIEW"),
            "review_reason": sub.get("review_reason"),
            "has_defect": bool(sub.get("has_defect")),
            "awaiting_documents": bool(getattr(rec, "awaiting_docs", False)),
            "comparisons": [{
                "field": name,
                "verdict": c.verdict.value.upper(),
                "leaning": c.leaning.value.upper() if c.leaning is not None else None,
                "si_value": getattr(c.si, "raw_text", None),
                "bl_value": getattr(c.bl, "raw_text", None),
                "si_numeric": _numeric(getattr(c.si, "normalised", None)),
                "bl_numeric": _numeric(getattr(c.bl, "normalised", None)),
                "si_evidence": _evidence(c.si),
                "bl_evidence": _evidence(c.bl),
                "strategy": c.strategy,
                "detail": c.detail,
            } for name, c in sorted((rec.comparisons or {}).items())],
            "events": [{"seq": e.seq, "stage": e.stage, "outcome": e.outcome,
                        "detail": (e.detail or "")[:4000]}
                       for e in _unique_seq(rec.trace or [])],
        })
    return rows


def _unique_seq(trace):
    """`stage_events` is UNIQUE (record_id, seq); the trace is the source of truth
    for order. Deduplicate defensively rather than letting an integrity error take
    down a 520-record insert."""
    seen, out = set(), []
    for e in trace:
        if e.seq in seen:
            continue
        seen.add(e.seq)
        out.append(e)
    return out


def _decided_by(rec) -> str | None:
    """'llm' when the model settled the category, 'rule' when deterministic logic did.

    Read from `Record.decided_by`, which the ARBITER sets at the moment it decides.

    The first version of this function sniffed the confidence number out of the
    trace string — 0.99 means structural, 0.90 means the body-intent rule. That is a
    claim about a cause with nothing asserting the cause, and it was wrong the moment
    a model happened to return 0.9. This project has paid for that mistake twice
    already; the fix is to record the fact where it is known, not to reconstruct it.
    """
    return getattr(rec, "decided_by", None)
