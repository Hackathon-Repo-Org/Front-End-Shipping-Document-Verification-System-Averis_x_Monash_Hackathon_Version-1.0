"""M12 — escalations out with evidence, human decisions back in.

P-HANDOFF: there is ONE file. v1.0 wrote `review_queue.json` and expected the human
to create a separate `resolved.json` — but the file the reviewer is handed is the
queue, so the natural action is to annotate it in place, and the next run overwrites
it. That is the exact trust-loss failure this module exists to prevent, arriving
through the file layout instead of the logic.

So: the queue carries a `"decision": null` field the human fills in, and the SAME
file is read back at the start of every run. Entries already decided are preserved
when the queue is rewritten.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Iterable, Mapping

from shipdoc.types import Decision, Record, Verdict

SCHEMA_NOTE = (
    "Fill in \"decision\" with one of: match | mismatch | cannot_determine. "
    "Leave it null if you have not reviewed the row. This file is READ BACK on the "
    "next run — your entries survive; do not copy them elsewhere."
)


def _entry(rec: Record, field: str, comparison) -> dict:
    """Self-sufficient: field, both raw values, both SourceRefs, the strategy that
    ran, and why it stopped. An entry that says only "uncertain" moves the whole job
    to the human instead of the 5% that needed one."""
    def side(fv):
        if fv is None:
            return {"raw_text": None, "normalised": None, "source": None, "label_seen": None}
        return {
            "raw_text": fv.raw_text,
            "normalised": None if fv.normalised is None else str(fv.normalised),
            "source": {"file": fv.source.file, "locator": fv.source.locator},
            "label_seen": fv.label_seen,
        }

    return {
        "email_id": rec.email_id,
        "field": field,
        "subject": rec.raw.get("subject", ""),
        "category": rec.category,
        "state": str(rec.state) if rec.state else None,
        "stopped_because": str(rec.reason) if rec.reason else None,
        "verdict": str(comparison.verdict) if comparison else None,
        "leaning": str(comparison.leaning) if comparison and comparison.leaning else None,
        "strategy": comparison.strategy if comparison else None,
        "detail": comparison.detail if comparison else None,
        "si": side(comparison.si) if comparison else side(None),
        "bl": side(comparison.bl) if comparison else side(None),
        "decision": None,
        "note": "",
    }


def rows_for(rec: Record) -> list[dict]:
    """One row per (email_id, field) that needs a human. Keying by email_id alone
    would let two escalations on different fields overwrite each other."""
    rows: list[dict] = []
    for field in list(rec.unresolved) + [f for f in rec.suspected if f not in rec.unresolved]:
        rows.append(_entry(rec, field, rec.comparisons.get(field)))
    if not rows and rec.state is not None and str(rec.state) != "resolved":
        rows.append(_entry(rec, "*", None))     # whole-record escalation
    return rows


def write_queue(records: Iterable[Record], path: Path,
                preserve: Mapping[tuple[str, str], dict] | None = None) -> None:
    """Rewrite the queue, carrying forward any decision a human already entered."""
    preserve = preserve or {}
    rows: list[dict] = []
    emitted: set[tuple[str, str]] = set()

    for rec in records:
        if rec.awaiting_docs:
            continue          # waiting for documents is not a review task
        if rec.state is not None and str(rec.state) == "resolved" and not rec.unresolved:
            continue
        for row in rows_for(rec):
            key = (row["email_id"], row["field"])
            prior = preserve.get(key)
            if prior is not None and prior.get("decision") is not None:
                row["decision"] = prior["decision"]
                row["note"] = prior.get("note", "")
                row["by"] = prior.get("by", "")
                row["at"] = prior.get("at", "")
            rows.append(row)
            emitted.add(key)

    # A decided row must persist even once its record no longer needs review — which
    # is the normal outcome, because applying the decision is what resolved it. Without
    # this the human's answer is honoured for exactly one run and then erased from the
    # file, and the next run forgets it. That is the same trust-loss failure
    # P-HANDOFF describes, arriving one step later.
    for key, prior in preserve.items():
        if key in emitted or prior.get("decision") is None:
            continue
        carried = dict(prior)
        carried["carried_forward"] = True
        rows.append(carried)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_README": SCHEMA_NOTE, "entries": rows}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def read_raw(path: Path) -> dict[tuple[str, str], dict]:
    """Every row from the queue file, decided or not, keyed by (email_id, field)."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = payload.get("entries", []) if isinstance(payload, dict) else payload
    return {(e["email_id"], e["field"]): e for e in entries
            if isinstance(e, dict) and "email_id" in e and "field" in e}


def load_decisions(path: Path) -> dict[tuple[str, str], Decision]:
    """Only rows a human actually filled in. An unparseable verdict is ignored
    rather than crashing the run — a typo in the queue must not lose the batch."""
    out: dict[tuple[str, str], Decision] = {}
    for key, row in read_raw(path).items():
        raw = row.get("decision")
        if raw is None:
            continue
        try:
            verdict = Verdict(str(raw).strip().lower())
        except ValueError:
            continue
        out[key] = Decision(email_id=key[0], field=key[1], verdict=verdict,
                            note=row.get("note", ""), by=row.get("by", ""),
                            at=row.get("at", ""))
    return out


def apply_decisions(rec: Record, decisions: Mapping[tuple[str, str], Decision]) -> Record:
    """Human answers override the comparator.

    `Comparison` is frozen, so this uses dataclasses.replace — which also makes
    idempotency trivially true: applying the same decision twice produces the same
    value, not a doubled one.
    """
    if not decisions:
        return rec
    for field, comparison in list(rec.comparisons.items()):
        d = decisions.get((rec.email_id, field))
        if d is None:
            continue
        # Idempotent: re-applying must not re-prefix. `human:human:text` would also
        # make the report's machine-vs-human distinction unreadable.
        base = comparison.strategy.split("human:")[-1]
        rec.comparisons[field] = dataclasses.replace(
            comparison,
            verdict=d.verdict,
            # A human-supplied verdict is marked, so the report can distinguish a
            # machine-verified result from a human-asserted one.
            strategy=f"human:{base}",
            detail=(f"human decision: {d.verdict}"
                    + (f" — {d.note}" if d.note else "")),
            leaning=None,
        )
    return rec
