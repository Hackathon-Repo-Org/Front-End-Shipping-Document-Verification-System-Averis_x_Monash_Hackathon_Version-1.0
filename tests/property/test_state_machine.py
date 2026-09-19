"""Stage 1 gate — M11 state machine.

The first two tests are regression guards for the fatal v1.0 defect: `all([])` is
True, so quantifying over an empty comparison map asserted RESOLVED and email_507
was reported clean.
"""
import itertools

import pytest

from shipdoc.errors import ReasonKey
from shipdoc.state.machine import evaluate, raise_state
from shipdoc.types import (
    Category,
    Comparison,
    Record,
    RecordState,
    STATE_PRECEDENCE,
    Verdict,
)

from conftest import CONFIG_DIR
from shipdoc.config import load_config


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG_DIR)


def make_record(**kw) -> Record:
    return Record(email_id=kw.pop("email_id", "email_001"), raw=kw.pop("raw", {}), **kw)


def comparison(field: str, verdict: Verdict) -> Comparison:
    return Comparison(field=field, verdict=verdict, si=None, bl=None,
                      strategy="test", detail="")


# --------------------------------------------------------------------------
# The v1.0 regression: all([]) is True
# --------------------------------------------------------------------------

def test_escalated_with_empty_comparisons_stays_escalated(cfg):
    """v1.0 defect C1. A stage escalated (email_507: MissingAttachmentError),
    comparisons is empty, and evaluate must NOT overwrite that with RESOLVED."""
    rec = make_record(category=Category.BL_COMPARISON)
    raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_NO_ATTACHMENT)
    assert rec.comparisons == {}

    evaluate(rec, cfg)

    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_NO_ATTACHMENT  # the original reason survives


def test_empty_comparisons_from_clean_state_escalates(cfg):
    """Even with no prior escalation, an empty map must never reach RESOLVED."""
    rec = make_record(category=Category.BL_COMPARISON)
    evaluate(rec, cfg)
    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_NO_VALUE


def test_six_of_seven_all_match_escalates(cfg):
    """v1.0 defect C2. A partial comparison map, every present verdict MATCH.
    Cardinality is asserted, not quantified, so this must escalate."""
    names = list(cfg.fields)
    assert len(names) == 7, "field registry must carry all seven compared fields"
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in names[:6]}

    evaluate(rec, cfg)

    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_NO_VALUE


def test_seven_of_seven_all_match_resolves(cfg):
    """Guards the two tests above from passing vacuously."""
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in cfg.fields}

    evaluate(rec, cfg)

    assert rec.state is RecordState.RESOLVED
    assert rec.defects == []
    assert rec.unresolved == []


def test_extra_unknown_field_escalates(cfg):
    """Set inequality, not length. A stray key with the right count still fails."""
    names = list(cfg.fields)
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in names[:6]}
    rec.comparisons["not_a_real_field"] = comparison("not_a_real_field", Verdict.MATCH)
    assert len(rec.comparisons) == len(cfg.fields)

    evaluate(rec, cfg)

    assert rec.state is RecordState.ESCALATED


# --------------------------------------------------------------------------
# evaluate's branches
# --------------------------------------------------------------------------

def test_no_category_escalates(cfg):
    rec = make_record(category=None)
    evaluate(rec, cfg)
    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_CLASSIFY


def test_non_comparison_category_resolves(cfg):
    rec = make_record(category=Category.SPAM)
    evaluate(rec, cfg)
    assert rec.state is RecordState.RESOLVED
    assert rec.comparisons == {}


def test_confirmed_mismatch_outranks_cannot_determine(cfg):
    """M11 step 4 / v2 change 4. A detected defect must not be discarded because
    another field was unreadable."""
    names = list(cfg.fields)
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in names}
    rec.comparisons[names[0]] = comparison(names[0], Verdict.MISMATCH)
    rec.comparisons[names[1]] = comparison(names[1], Verdict.CANNOT_DETERMINE)

    evaluate(rec, cfg)

    assert rec.state is RecordState.RESOLVED
    assert rec.defects == [names[0]]
    assert rec.unresolved == [names[1]]


def test_cannot_determine_alone_escalates(cfg):
    names = list(cfg.fields)
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in names}
    rec.comparisons[names[1]] = comparison(names[1], Verdict.CANNOT_DETERMINE)

    evaluate(rec, cfg)

    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_NO_VALUE
    assert rec.unresolved == [names[1]]


def test_failed_is_never_downgraded_by_evaluate(cfg):
    """run_stage sets FAILED unconditionally; evaluate must not undo it."""
    rec = make_record(category=Category.BL_COMPARISON)
    rec.comparisons = {n: comparison(n, Verdict.MATCH) for n in cfg.fields}
    rec.state, rec.reason = RecordState.FAILED, ReasonKey.ERR_UNHANDLED

    evaluate(rec, cfg)

    assert rec.state is RecordState.FAILED


# --------------------------------------------------------------------------
# raise_state monotonicity — property test over every assignment order
# --------------------------------------------------------------------------

ALL_STATES = tuple(RecordState)


@pytest.mark.parametrize("seq", [
    s for n in (1, 2, 3)
    for s in itertools.product(ALL_STATES, repeat=n)
])
def test_raise_state_is_monotone(seq):
    """For every sequence of assignments, the final state is the maximum by
    precedence. raise_state may only move UP the ladder."""
    rec = Record(email_id="email_001", raw={})
    seen_max = None
    for s in seq:
        raise_state(rec, s, None)
        seen_max = s if seen_max is None else max(
            seen_max, s, key=lambda x: STATE_PRECEDENCE[x])
        # invariant holds after every single step, not just at the end
        assert rec.state is seen_max
    assert rec.state is max(seq, key=lambda x: STATE_PRECEDENCE[x])


@pytest.mark.parametrize("seq", [
    s for s in itertools.permutations(ALL_STATES, 3)
])
def test_raise_state_never_downgrades(seq):
    rec = Record(email_id="email_001", raw={})
    prev = None
    for s in seq:
        raise_state(rec, s, None)
        if prev is not None:
            assert STATE_PRECEDENCE[rec.state] >= STATE_PRECEDENCE[prev]
        prev = rec.state


def test_raise_state_keeps_reason_of_the_winning_state():
    rec = Record(email_id="email_001", raw={})
    raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_NO_ATTACHMENT)
    raise_state(rec, RecordState.RESOLVED, None)          # rejected — lower
    assert rec.state is RecordState.ESCALATED
    assert rec.reason is ReasonKey.ERR_NO_ATTACHMENT
    raise_state(rec, RecordState.FAILED, ReasonKey.ERR_UNHANDLED)   # accepted
    assert rec.state is RecordState.FAILED
    assert rec.reason is ReasonKey.ERR_UNHANDLED


def test_record_state_has_no_default():
    """HARD RULE 1. A default of RESOLVED is the most dangerous line in the system."""
    assert Record(email_id="email_001", raw={}).state is None
