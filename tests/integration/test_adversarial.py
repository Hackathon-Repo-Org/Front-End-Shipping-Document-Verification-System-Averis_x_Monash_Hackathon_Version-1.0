"""The adversarial fixtures (emails 997/998/999) as a regression suite.

These are SYNTHETIC and hand-written by this team — see
tests/fixtures/adversarial/README.md. They are not from the organisers and there is
no official answer key for them. Every expectation here is our own reasoning, and
where the system's behaviour is a judgement call rather than plainly right, the test
says so in its name and docstring instead of pretending otherwise.

They exist because a precision of 1.000 measured on the provided corpus is a fact
about that corpus. These three emails are the cheapest evidence available about
anything else.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shipdoc.classify.intent import awaiting_documents, requests_bl_comparison
from shipdoc.config import load_config
from shipdoc.ingest.loader_port import LoaderInbox
from shipdoc.pipeline import _CTX, run_corpus
from shipdoc.types import Verdict

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "adversarial"


@pytest.fixture(scope="module")
def records(tmp_path_factory):
    """Run the pipeline over the three fixtures once, with no LLM.

    `llm=None` on purpose: every expectation below must hold on a machine with no
    Ollama, or the suite is not a regression test, it is a weather report.
    """
    cfg = load_config(str(REPO / "config"))
    _CTX["cache_dir"] = tmp_path_factory.mktemp("adv_cache")
    result = run_corpus(LoaderInbox(str(FIXTURES)), cfg, llm=None)
    return {r.email_id: r for r in result["records"]}


def _verdict(rec, field):
    return rec.comparisons[field].verdict


# ----------------------------------------------------------------- email_997

def test_997_is_a_comparison_request(records):
    assert records["email_997"].category == "BL_COMPARISON"


def test_997_catches_the_port_swap(records):
    """The genuine defect: POL and POD are exchanged between the two documents."""
    rec = records["email_997"]
    assert _verdict(rec, "port_of_loading") is Verdict.MISMATCH
    assert _verdict(rec, "port_of_discharge") is Verdict.MISMATCH


def test_997_defect_set_is_exactly_the_two_ports(records):
    """The whole point of Phase 10: no fabricated defects alongside the real ones."""
    assert sorted(records["email_997"].defects) == ["port_of_discharge",
                                                    "port_of_loading"]


def test_997_legal_suffix_punctuation_is_not_a_defect(records):
    """`SDN BHD` vs `SDN. BHD.` — the same suffix, spelled with full stops."""
    assert _verdict(records["email_997"], "shipper") is Verdict.MATCH


def test_997_european_decimal_separators_are_not_a_defect(records):
    """`22,450.50 KGS` vs `22.450,50 KGS` are the same quantity."""
    assert _verdict(records["email_997"], "gross_weight_kg") is Verdict.MATCH


def test_997_same_as_consignee_resolves_to_the_consignee(records):
    """Fix 2. The SI's notify party points at its own consignee, which is what the
    BL spells out. Comparing the pointer as a literal name was a false positive."""
    rec = records["email_997"]
    assert _verdict(rec, "notify_party") is Verdict.MATCH
    si = rec.comparisons["notify_party"].si
    assert si.resolved_from == "consignee"
    assert "SAME AS CONSIGNEE" in si.reference_text.upper()


def test_997_container_count_compares_the_count_not_the_size(records):
    """`2 x 40'HC` vs `2 x 4O'HC` (letter O). The COUNT is 2 on both sides.

    This asserts the behaviour we ship, not the behaviour we want: the homoglyph
    corrupts the container SIZE, which this system does not model. Recorded in
    HANDOVER.md as a field-definition gap. If container size is ever added as a
    compared field, this test should start failing and be rewritten.
    """
    assert _verdict(records["email_997"], "container_count") is Verdict.MATCH


# ----------------------------------------------------------------- email_998

def test_998_body_instruction_beats_the_subject_line(records):
    """Fix 3. Subject says INVOICE DISPUTE; body says audit the BL against the SI."""
    assert records["email_998"].category == "BL_COMPARISON"


def test_998_rule_is_deterministic_and_reads_the_body_only():
    """The rule must not depend on the model, and must not read the subject."""
    import json

    raw = json.loads((FIXTURES / "inbox" / "email_998.json").read_text("utf-8"))

    class _R:
        pass

    r = _R()
    r.raw = raw
    assert requests_bl_comparison(r) is True

    # Strip the body: the subject alone must NOT trigger the rule.
    r2 = _R()
    r2.raw = dict(raw, body="")
    assert requests_bl_comparison(r2) is False


def test_998_escalates_rather_than_resolving_silently(records):
    """It asks for an urgent audit and attaches nothing. A human must see it."""
    rec = records["email_998"]
    assert rec.state.value == "escalated"
    assert not rec.comparisons


def test_998_awaiting_docs_rule_now_runs_and_declines():
    """Documents the REASON, not just the outcome.

    Before Fix 3 this rule never ran on this record, because the category
    short-circuited first. It runs now and returns False, because
    `_EXPECTED_PRESENT` matches "forgot to attach" — a NEGATED attachment claim it
    cannot distinguish from a positive one. That gap is recorded in HANDOVER.md.

    If someone later teaches the rule about negation, this test will fail and should
    be updated deliberately, rather than the behaviour changing unnoticed.
    """
    import json

    raw = json.loads((FIXTURES / "inbox" / "email_998.json").read_text("utf-8"))

    class _R:
        pass

    r = _R()
    r.raw = raw
    assert awaiting_documents(r) is False


# ----------------------------------------------------------------- email_999

def test_999_is_a_comparison_request(records):
    assert records["email_999"].category == "BL_COMPARISON"


def test_999_draft_bill_of_lading_is_recognised_as_a_bl(records):
    """The BL is titled `DRAFT BILL OF LADING` and must not be rejected."""
    assert "BL" in records["email_999"].documents


def test_999_bare_containers_label_is_extracted(records):
    """Fix 1 (secondary). `Containers: 3 x 40'HC` is identical on both sides."""
    assert _verdict(records["email_999"], "container_count") is Verdict.MATCH


def test_999_net_weight_is_never_read_as_gross(records):
    """The trap: the BL's NET WEIGHT is the SI's GROSS figure.

    A system that treats WEIGHT as one field reports a confident MATCH on two
    different quantities. The gross value on the BL is `N/A`, so anything other than
    a non-match here means the anti-synonym list failed.
    """
    rec = records["email_999"]
    bl_gross = rec.fields["BL"].get("gross_weight_kg")
    assert bl_gross is None or bl_gross.normalised is None
    assert _verdict(rec, "gross_weight_kg") is not Verdict.MATCH


def test_999_sentinel_notify_party_is_not_silently_matched(records):
    """`_______` must never compare equal to a real company name."""
    assert _verdict(records["email_999"], "notify_party") is not Verdict.MATCH


@pytest.mark.xfail(reason="UN/LOCODE port resolution is switched OFF by measurement "
                          "— see docs/decisions/port-resolution.md. These two are "
                          "known false positives and are the third data point for "
                          "the recorded fix direction.",
                   strict=True)
def test_999_bare_locodes_match_their_named_ports(records):
    """`MYTPP` is Tanjung Pelepas and `JPNGO` is Nagoya. We report defects.

    Marked xfail(strict) deliberately: if someone flips the port-resolution flag,
    this test goes from expected-fail to unexpected-PASS and the suite fails, forcing
    a conversation rather than a silent behaviour change.
    """
    rec = records["email_999"]
    assert _verdict(rec, "port_of_loading") is Verdict.MATCH
    assert _verdict(rec, "port_of_discharge") is Verdict.MATCH


# ------------------------------------------------- Fix 1, stated as a contract

def test_unmatched_label_yields_caution_not_a_defect(records):
    """Fix 1, as a general rule rather than as one email's symptom.

    A field the SI supplies and the BL never labels at all is an EXTRACTION MISS —
    a fact about our synonym list, not about the carrier — and must escalate rather
    than report a defect. The synonym list will always be incomplete; this is what
    makes incompleteness safe.
    """
    from shipdoc.compare.comparators import _missing
    from shipdoc.types import FieldSpec, Method, SourceRef
    from shipdoc.types import FieldValue

    spec = FieldSpec(name="gross_weight_kg", type="quantity", required=True,
                     synonyms=())
    si = FieldValue(field="gross_weight_kg", raw_text="45,120.00 KGS",
                    normalised=45120, source=SourceRef(file="si.txt", locator="l1"),
                    method=Method.NATIVE_TEXT, label_seen="Gross Weight:")

    # BL key absent entirely -> label never found -> caution.
    absent = _missing(si, None, spec, "quantity")
    assert absent.verdict is Verdict.CANNOT_DETERMINE
    assert absent.leaning is None, "an extraction miss is not evidence of a defect"

    # BL key present with no usable value -> the label WAS found and the value is
    # blank or a sentinel -> the carrier really did omit it -> defect.
    blank = FieldValue(field="gross_weight_kg", raw_text="N/A", normalised=None,
                       source=SourceRef(file="bl.txt", locator="l1"),
                       method=Method.NATIVE_TEXT, label_seen="Gross Weight:")
    assert _missing(si, blank, spec, "quantity").verdict is Verdict.MISMATCH


def test_labels_seen_is_recorded_for_every_document(records):
    """Fix 1's display half: `inspect` cannot explain a miss without this."""
    rec = records["email_999"]
    assert "SI" in rec.labels_seen and "BL" in rec.labels_seen
    assert "shipper" in rec.labels_seen["BL"]


def test_unresolvable_reference_is_caution_not_a_defect():
    """Fix 2's failure mode. A pointer we cannot follow is never a defect."""
    from shipdoc.normalise import UNRESOLVED_REFERENCE
    from shipdoc.compare.comparators import _missing
    from shipdoc.types import FieldSpec, FieldValue, Method, SourceRef

    spec = FieldSpec(name="notify_party", type="text", required=True, synonyms=())
    si = FieldValue(field="notify_party", raw_text="ACME LTD", normalised="ACME LTD",
                    source=SourceRef(file="si.txt", locator="l1"),
                    method=Method.NATIVE_TEXT, label_seen="Notify:")
    dangling = FieldValue(field="notify_party", raw_text="SAME AS CONSIGNEE",
                          normalised=None,
                          source=SourceRef(file="bl.txt", locator="l1"),
                          method=Method.NATIVE_TEXT, label_seen=UNRESOLVED_REFERENCE,
                          reference_text="SAME AS CONSIGNEE")
    c = _missing(si, dangling, spec, "text")
    assert c.verdict is Verdict.CANNOT_DETERMINE
    assert c.leaning is None
