"""M11 — the only module that may assign `Record.state`.

Two properties carry the system's central invariant:

  * `raise_state` is monotone. A state set by a raising stage can never be
    downgraded by a later one.
  * `evaluate` ASSERTS cardinality against the field registry. It does not
    quantify over the dict it was handed — `all([])` is True, and that is
    exactly how v1.0 reported email_507 as clean.
"""
from __future__ import annotations

from shipdoc.errors import ReasonKey
from shipdoc.types import (
    Config,
    Record,
    RecordState,
    STATE_PRECEDENCE,
    Verdict,
)


def raise_state(rec: Record, new: RecordState, reason: ReasonKey | None = None) -> None:
    """Monotone. May only move UP the precedence ladder. Never downgrades."""
    cur = rec.state
    if cur is None or STATE_PRECEDENCE[new] > STATE_PRECEDENCE[cur]:
        rec.state, rec.reason = new, reason


def evaluate(rec: Record, cfg: Config) -> Record:
    # 1 — classification must have succeeded
    if rec.category is None:
        raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_CLASSIFY)
        return rec

    # 2 — non-comparison records resolve HERE, never inline in the pipeline
    if rec.category != cfg.comparison_category:
        raise_state(rec, RecordState.RESOLVED)
        return rec

    # 2b — the documents have not been sent yet. Nothing is missing, nothing is
    #      wrong, and there is nothing to compare: this resolves clean and is kept out
    #      of the review queue. It is NOT a cardinality failure, so it is decided
    #      before step 3.
    if rec.awaiting_docs:
        raise_state(rec, RecordState.RESOLVED)
        return rec

    # 3 — CARDINALITY IS ASSERTED, NOT QUANTIFIED. This is the v1.0 defect.
    if set(rec.comparisons) != set(cfg.fields):
        raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_NO_VALUE)
        return rec

    verdicts = {f: c.verdict for f, c in rec.comparisons.items()}
    rec.defects    = [f for f, v in verdicts.items() if v is Verdict.MISMATCH]
    rec.unresolved = [f for f, v in verdicts.items() if v is Verdict.CANNOT_DETERMINE]
    # Patch 02 §3 — "uncertain but leaning negative" is distinguishable from
    # "no information at all"; both are CANNOT_DETERMINE on the verdict alone.
    rec.suspected  = [f for f, c in rec.comparisons.items()
                      if c.verdict is Verdict.CANNOT_DETERMINE
                      and c.leaning is Verdict.MISMATCH]

    # 4 — a CONFIRMED defect outranks an unknown field (v2 change 4, costed in M11)
    if rec.defects:
        raise_state(rec, RecordState.RESOLVED)
        return rec
    if rec.unresolved:
        raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_NO_VALUE)
        return rec
    raise_state(rec, RecordState.RESOLVED)
    return rec
