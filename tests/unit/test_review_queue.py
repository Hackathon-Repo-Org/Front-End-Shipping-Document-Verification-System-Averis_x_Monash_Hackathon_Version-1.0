"""Stage 8 gate — M12 review queue.

P-HANDOFF is the property under test: there is ONE file. The reviewer annotates the
file they were handed, and the next run reads that same file back.
"""
import json

import pytest

from conftest import CONFIG_DIR, ROOT
from shipdoc.config import load_config
from shipdoc.review.queue import (
    apply_decisions,
    load_decisions,
    read_raw,
    write_queue,
)
from shipdoc.types import (
    Comparison,
    Decision,
    FieldValue,
    Method,
    Record,
    RecordState,
    ReasonKey,
    SourceRef,
    Verdict,
)


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG_DIR)


def fv(field, raw, norm="X"):
    return FieldValue(field, raw, norm, SourceRef("attachments/f.txt", "line 7"),
                      Method.NATIVE_TEXT, f"{field}:")


def make_rec(eid="email_042", **kw):
    rec = Record(email_id=eid, raw={"subject": "TO CONFIRM DOCS"}, **kw)
    return rec


def escalated_record(cfg):
    rec = make_rec(category=cfg.comparison_category)
    rec.comparisons = {
        n: Comparison(n, Verdict.MATCH, fv(n, "A"), fv(n, "A"), "text", "ok")
        for n in cfg.fields
    }
    rec.comparisons["consignee"] = Comparison(
        "consignee", Verdict.CANNOT_DETERMINE, fv("consignee", "ACME LTD"),
        fv("consignee", "ACME LIMITED"), "text", "similarity 0.91 (grey band)",
        leaning=Verdict.MISMATCH)
    rec.state, rec.reason = RecordState.ESCALATED, ReasonKey.ERR_NO_VALUE
    rec.unresolved = ["consignee"]
    rec.suspected = ["consignee"]
    return rec


# --------------------------------------------------------------------------
# The queue is self-sufficient
# --------------------------------------------------------------------------

def test_queue_entry_carries_everything_a_reviewer_needs(cfg, tmp_path):
    """"Uncertain" alone moves the whole job to the human instead of the 5% that
    needed one."""
    p = tmp_path / "review_queue.json"
    write_queue([escalated_record(cfg)], p)
    row = json.loads(p.read_text(encoding="utf-8"))["entries"][0]

    assert row["email_id"] == "email_042" and row["field"] == "consignee"
    assert row["si"]["raw_text"] == "ACME LTD"
    assert row["bl"]["raw_text"] == "ACME LIMITED"
    assert row["si"]["source"]["locator"] == "line 7"
    assert row["bl"]["source"]["file"].endswith(".txt")
    assert row["strategy"] == "text"
    assert "grey band" in row["detail"]
    assert row["stopped_because"] == "err_no_value"
    assert row["leaning"] == "mismatch"
    assert row["decision"] is None


def test_queue_keys_by_email_and_field_not_email_alone(cfg, tmp_path):
    """Two escalations on different fields of one email must not overwrite."""
    rec = escalated_record(cfg)
    rec.comparisons["shipper"] = Comparison(
        "shipper", Verdict.CANNOT_DETERMINE, fv("shipper", "A"), fv("shipper", "B"),
        "text", "grey", leaning=Verdict.MISMATCH)
    rec.unresolved = ["consignee", "shipper"]
    p = tmp_path / "q.json"
    write_queue([rec], p)
    keys = set(read_raw(p))
    assert keys == {("email_042", "consignee"), ("email_042", "shipper")}


def test_resolved_records_are_not_queued(cfg, tmp_path):
    rec = make_rec(category=cfg.comparison_category)
    rec.comparisons = {n: Comparison(n, Verdict.MATCH, fv(n, "A"), fv(n, "A"), "text", "")
                       for n in cfg.fields}
    rec.state = RecordState.RESOLVED
    p = tmp_path / "q.json"
    write_queue([rec], p)
    assert read_raw(p) == {}


def test_queue_explains_how_to_use_itself(cfg, tmp_path):
    p = tmp_path / "q.json"
    write_queue([escalated_record(cfg)], p)
    note = json.loads(p.read_text(encoding="utf-8"))["_README"]
    assert "decision" in note and "read back" in note.lower()


# --------------------------------------------------------------------------
# P-HANDOFF — one file, edited in place, survives the rewrite
# --------------------------------------------------------------------------

def test_a_filled_in_decision_survives_a_rewrite(cfg, tmp_path):
    """The exact trust-loss failure this module exists to prevent."""
    p = tmp_path / "review_queue.json"
    write_queue([escalated_record(cfg)], p)

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["entries"][0]["decision"] = "mismatch"
    payload["entries"][0]["note"] = "consignee is a different legal entity"
    p.write_text(json.dumps(payload), encoding="utf-8")

    prior = read_raw(p)
    write_queue([escalated_record(cfg)], p, preserve=prior)

    row = json.loads(p.read_text(encoding="utf-8"))["entries"][0]
    assert row["decision"] == "mismatch", "the reviewer's work was destroyed"
    assert row["note"] == "consignee is a different legal entity"


def test_a_decision_survives_after_it_resolves_its_own_record(cfg, tmp_path):
    """The subtle half of P-HANDOFF. Applying a decision is what RESOLVES the record,
    so on the next write the field is no longer unresolved and its row would vanish —
    honouring the human's answer for exactly one run and then forgetting it."""
    p = tmp_path / "review_queue.json"
    write_queue([escalated_record(cfg)], p)

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["entries"][0]["decision"] = "match"
    p.write_text(json.dumps(payload), encoding="utf-8")
    prior = read_raw(p)

    # the record now comes back fully resolved, needing no review at all
    resolved = make_rec(category=cfg.comparison_category)
    resolved.comparisons = {
        n: Comparison(n, Verdict.MATCH, fv(n, "A"), fv(n, "A"), "text", "")
        for n in cfg.fields}
    resolved.state = RecordState.RESOLVED

    write_queue([resolved], p, preserve=prior)

    surviving = load_decisions(p)
    assert ("email_042", "consignee") in surviving, \
        "the reviewer's answer was erased the run after it took effect"
    assert surviving[("email_042", "consignee")].verdict is Verdict.MATCH


def test_carried_forward_rows_are_marked(cfg, tmp_path):
    p = tmp_path / "q.json"
    write_queue([escalated_record(cfg)], p)
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["entries"][0]["decision"] = "match"
    p.write_text(json.dumps(payload), encoding="utf-8")
    write_queue([], p, preserve=read_raw(p))
    row = json.loads(p.read_text(encoding="utf-8"))["entries"][0]
    assert row.get("carried_forward") is True


def test_load_decisions_reads_only_filled_rows(cfg, tmp_path):
    p = tmp_path / "q.json"
    write_queue([escalated_record(cfg)], p)
    assert load_decisions(p) == {}

    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["entries"][0]["decision"] = "match"
    p.write_text(json.dumps(payload), encoding="utf-8")

    d = load_decisions(p)
    assert set(d) == {("email_042", "consignee")}
    assert d[("email_042", "consignee")].verdict is Verdict.MATCH


def test_a_typo_in_the_queue_does_not_lose_the_batch(cfg, tmp_path):
    p = tmp_path / "q.json"
    write_queue([escalated_record(cfg)], p)
    payload = json.loads(p.read_text(encoding="utf-8"))
    payload["entries"][0]["decision"] = "MATHC"      # typo
    p.write_text(json.dumps(payload), encoding="utf-8")
    assert load_decisions(p) == {}                   # ignored, not raised


def test_missing_queue_file_is_not_an_error(tmp_path):
    assert load_decisions(tmp_path / "nope.json") == {}
    assert read_raw(tmp_path / "nope.json") == {}


def test_corrupt_queue_file_is_not_an_error(tmp_path):
    p = tmp_path / "q.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_decisions(p) == {}


# --------------------------------------------------------------------------
# apply_decisions
# --------------------------------------------------------------------------

def test_decision_overrides_the_comparator(cfg):
    rec = escalated_record(cfg)
    d = {("email_042", "consignee"): Decision("email_042", "consignee",
                                              Verdict.MISMATCH, note="different entity")}
    apply_decisions(rec, d)
    c = rec.comparisons["consignee"]
    assert c.verdict is Verdict.MISMATCH
    assert c.strategy.startswith("human:"), "a human verdict must be distinguishable"
    assert "different entity" in c.detail
    assert c.leaning is None


def test_apply_decisions_is_idempotent(cfg):
    rec = escalated_record(cfg)
    d = {("email_042", "consignee"): Decision("email_042", "consignee", Verdict.MATCH)}
    apply_decisions(rec, d)
    first = rec.comparisons["consignee"]
    apply_decisions(rec, d)
    apply_decisions(rec, d)
    assert rec.comparisons["consignee"] == first


def test_decision_moves_a_record_out_of_escalation(cfg):
    """The whole point: a human answer resolves the record in the same single pass."""
    from shipdoc.state.machine import evaluate
    rec = escalated_record(cfg)
    rec.state, rec.reason = None, None            # fresh run
    apply_decisions(rec, {("email_042", "consignee"):
                          Decision("email_042", "consignee", Verdict.MATCH)})
    evaluate(rec, cfg)
    assert rec.state is RecordState.RESOLVED
    assert rec.unresolved == [] and rec.suspected == []


def test_decisions_for_other_records_are_ignored(cfg):
    rec = escalated_record(cfg)
    before = dict(rec.comparisons)
    apply_decisions(rec, {("email_999", "consignee"):
                          Decision("email_999", "consignee", Verdict.MATCH)})
    assert rec.comparisons == before


def test_no_decisions_is_a_no_op(cfg):
    rec = escalated_record(cfg)
    before = dict(rec.comparisons)
    assert apply_decisions(rec, {}).comparisons == before
