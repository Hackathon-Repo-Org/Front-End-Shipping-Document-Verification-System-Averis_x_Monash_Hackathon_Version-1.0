"""Stage 4 gate — detect, extract/text, route/by_name, normalise, compare.

Golden cases here are regression guards for defects that were already found once.
"""
from decimal import Decimal

import pytest

from conftest import CONFIG_DIR, DATASET_DIR, ROOT, TEST_CACHE
from shipdoc.compare.comparators import COMPARATORS, compare_all
from shipdoc.config import load_config
from shipdoc.detect import mime as M
from shipdoc.errors import DocumentTypeError, MissingAttachmentError
from shipdoc.extract.text import TextExtractor
from shipdoc.ingest.loader_port import LoaderInbox
from shipdoc.normalise import Normaliser
from shipdoc.normalise.labels import LabelIndex, canon_label, strip_non_ascii
from shipdoc.normalise.sentinels import compile_sentinels, is_sentinel, strip_units
from shipdoc.normalise.values import parse_container_count, parse_decimal, parse_quantity
from shipdoc.route.by_name import route_by_name
from shipdoc.types import FIELD_TYPES, Record, RecordState, Verdict


@pytest.fixture(scope="module")
def cfg():
    return load_config(CONFIG_DIR)


@pytest.fixture(scope="module")
def inbox():
    return LoaderInbox(str(DATASET_DIR))


@pytest.fixture(scope="module")
def run(cfg, inbox):
    from shipdoc.pipeline import run_corpus
    r = run_corpus(inbox, cfg, llm=None, decisions={}, cache_dir=TEST_CACHE)
    return {"recs": {x.email_id: x for x in r["records"]},
            "sub": r["submission"], "summary": r["summary"]}


# --------------------------------------------------------------------------
# M05 detect
# --------------------------------------------------------------------------

def test_docx_and_xlsx_are_distinguished_not_both_zip(inbox):
    """The most common detection bug in this domain: both are PK\\x03\\x04."""
    assert M.detect(inbox.read_bytes("attachments/email_055_BL.docx"), "x.docx").mime == M.MIME_DOCX
    assert M.detect(inbox.read_bytes("attachments/email_005_BL.xlsx"), "x.xlsx").mime == M.MIME_XLSX


def test_detect_handles_zero_byte_file():
    d = M.detect(b"", "empty.txt")
    assert d.mime == M.MIME_UNKNOWN and d.confidence == 0.0


def test_detect_finds_pdf_behind_a_bom_or_whitespace():
    assert M.detect(b"\xef\xbb\xbf   \n%PDF-1.7\n...", "x.pdf").mime == M.MIME_PDF


def test_detect_disagrees_is_a_signal_not_an_error(inbox):
    d = M.detect(inbox.read_bytes("attachments/email_005_BL.xlsx"), "mislabelled.txt")
    assert d.disagrees is True
    assert d.mime == M.MIME_XLSX


def test_detect_reads_a_bounded_prefix_only():
    big = b"%PDF-1.4" + b"\x00" * (50 * 1024 * 1024)
    assert M.detect(big, "big.pdf").mime == M.MIME_PDF


# --------------------------------------------------------------------------
# M08 route/by_name
# --------------------------------------------------------------------------

def test_golden_507_and_509_missing_attachment(run):
    """The v1.0 regression: one attachment must be missing_attachment, and must
    never be compared against nothing."""
    for eid in ("email_507", "email_509"):
        entry, rec = run["sub"][eid], run["recs"][eid]
        assert entry["status"] == "NEEDS_REVIEW", eid
        assert entry["review_reason"] == "missing_attachment", eid
        assert entry["has_defect"] is False and entry["defect_fields"] == []
        assert rec.state is RecordState.ESCALATED
        assert rec.comparisons == {}, "nothing may be compared against a missing file"


def test_route_binds_the_filename_number_to_the_record():
    """A cross-linked attachment would compare the wrong pair, confidently."""
    r = Record(email_id="email_012", raw={"attachments": [
        "attachments/email_013_SI.txt", "attachments/email_012_BL.txt"]})
    with pytest.raises(DocumentTypeError, match="belongs to email_013"):
        route_by_name(r)


def test_route_detects_a_role_collision():
    r = Record(email_id="email_012", raw={"attachments": [
        "attachments/email_012_BL.txt", "attachments/email_012_bl.txt"]})
    with pytest.raises(DocumentTypeError, match="both parse as BL"):
        route_by_name(r)


def test_route_rejects_unanchored_variant_names():
    """Open Item 6, decided: anchored at both ends, so `_BL_final` does not match."""
    r = Record(email_id="email_012", raw={"attachments": [
        "attachments/email_012_SI.txt", "attachments/email_012_BL_final.txt"]})
    with pytest.raises(DocumentTypeError):
        route_by_name(r)


def test_route_with_no_attachments_is_missing_attachment():
    with pytest.raises(MissingAttachmentError):
        route_by_name(Record(email_id="email_002", raw={"attachments": []}))


# --------------------------------------------------------------------------
# M09 sentinels — the most likely silent-pass path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "N/A", "n/a", "NA", "TBA", "tbd", "NIL", "---", "_______", "", "   ",
    "_______ MTS", "N/A KGS", "_______MTS",
])
def test_sentinels_match_every_observed_spelling(cfg, raw):
    assert is_sentinel(raw, compile_sentinels(cfg.sentinels)), raw


@pytest.mark.parametrize("raw", ["21,577 KG", "1 x 40'HC", "MOORIM SP CO., LTD", "0"])
def test_sentinels_do_not_eat_real_values(cfg, raw):
    assert not is_sentinel(raw, compile_sentinels(cfg.sentinels)), raw


def test_units_are_stripped_before_the_sentinel_test():
    """`_______ MTS` must match `^_+$` AFTER the unit is removed, or it never fires."""
    assert strip_units("_______ MTS") == "_______"


def test_golden_516_sentinel_never_matches_a_sentinel(run, cfg):
    """email_516_SI.txt carries `Gross Weight毛重(KGS): N/A`. Two sentinels are equal
    as strings and must never be reported as a clean match."""
    rec = run["recs"]["email_516"]
    c = rec.comparisons["gross_weight_kg"]
    assert c.verdict is not Verdict.MATCH, f"sentinel compared MATCH: {c.detail}"
    if c.si is not None:
        assert c.si.normalised is None, "a sentinel must normalise to None (T5)"


def test_no_comparator_has_an_identity_short_circuit():
    """`if si.raw == bl.raw: return MATCH` re-opens the sentinel hole completely."""
    import ast
    import inspect
    from shipdoc.compare import comparators as mod
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.Eq):
            src = ast.unparse(node)
            assert "raw_text" not in src, f"identity short-circuit on raw text: {src}"


# --------------------------------------------------------------------------
# M09 labels — P-CJK and P-NET
# --------------------------------------------------------------------------

def test_cjk_label_is_normalised_before_lookup(cfg):
    """`Gross Weight毛重(KGS):` is a real label on a compared field."""
    assert strip_non_ascii("Gross Weight毛重(KGS):") == "Gross Weight(KGS):"
    hit = LabelIndex(cfg).match("Gross Weight毛重(KGS): N/A")
    assert hit is not None and hit[0] == "gross_weight_kg"


def test_net_weight_is_never_taken_as_gross(cfg):
    """P-NET. Longest-match alone prefers `NET WEIGHT:` and compares net vs gross."""
    assert LabelIndex(cfg).match("NET WEIGHT: _______ MTS") is None


def test_longest_label_wins(cfg):
    idx = LabelIndex(cfg)
    field, label, value = idx.match("Port of Loading (POL): PORT KLANG, MALAYSIA")
    assert field == "port_of_loading"
    assert "(POL)" in label and "(POL)" not in value


def test_to_the_order_of_maps_to_consignee(cfg):
    """x37 in the corpus, and nobody would have invented it."""
    assert LabelIndex(cfg).match("To the Order of: SHINHAN BANK")[0] == "consignee"


# --------------------------------------------------------------------------
# M09 values
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("21,577", Decimal("21577")), ("1,234,567", Decimal("1234567")),
    ("22000.10", Decimal("22000.10")), ("1.5", Decimal("1.5")),
])
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == expected


def test_quantity_converts_metric_tonnes(cfg):
    spec = cfg.fields["gross_weight_kg"]
    assert parse_quantity("21.577 MT", spec)[0] == Decimal("21577.000")


def test_unrecognised_unit_is_none_not_a_guess(cfg):
    assert parse_quantity("500 FURLONGS", cfg.fields["gross_weight_kg"])[0] is None


@pytest.mark.parametrize("raw,expected", [
    ("1 x 40'HC", 1), ("3 x 40'HC", 3), ("6 x 20'GP", 6),
    ("15 x 40'HC", 15), ("10 x 20'FCL", 10),
])
def test_container_count_takes_the_count_not_the_size(cfg, raw, expected):
    assert parse_container_count(raw, cfg.fields["container_count"])[0] == expected


def test_multi_size_shipment_is_cannot_determine(cfg):
    """P-MULTISIZE: summing gives 3, which matches `3 x 40'HC` — a different ship."""
    v, why = parse_container_count("2 x 40'HC + 1 x 20'GP", cfg.fields["container_count"])
    assert v is None and "multi_size" in why


# --------------------------------------------------------------------------
# M10 — the cardinality contract
# --------------------------------------------------------------------------

def test_comparator_registry_matches_the_declared_field_types():
    """The stage-4 half of the FIELD_TYPES contract recorded in types.py."""
    assert set(COMPARATORS) == FIELD_TYPES


def test_compare_all_emits_exactly_the_registry_even_when_both_sides_are_empty(cfg):
    out = compare_all({}, {}, cfg)
    assert set(out) == set(cfg.fields)
    assert all(c.verdict is Verdict.CANNOT_DETERMINE for c in out.values())


def test_cardinality_property_holds_for_every_compared_record(run, cfg):
    """T4. A partial field map must never yield a partial comparison map."""
    for eid, rec in run["recs"].items():
        if rec.comparisons:
            assert set(rec.comparisons) == set(cfg.fields), eid


def test_si_present_bl_absent_is_a_mismatch_not_an_unknown(cfg):
    """The SI is authoritative: a field the carrier omitted is a defect."""
    from shipdoc.types import FieldValue, Method, SourceRef
    si = {"consignee": FieldValue("consignee", "ACME LTD", "ACME LTD",
                                  SourceRef("f", "line 1"), Method.NATIVE_TEXT, "Consignee:")}
    out = compare_all(si, {}, cfg)
    assert out["consignee"].verdict is Verdict.MISMATCH
    assert out["consignee"].leaning is None


def test_grey_band_is_cannot_determine_leaning_mismatch(cfg):
    from shipdoc.types import FieldValue, Method, SourceRef
    def fv(v):
        return FieldValue("shipper", v, v, SourceRef("f", "l"), Method.NATIVE_TEXT, "Shipper:")
    out = compare_all({"shipper": fv("ACME TRADING SDN BHD KUALA LUMPUR")},
                      {"shipper": fv("ACME TRADING SDN BHD KUALA LUMPR")}, cfg)
    c = out["shipper"]
    if c.verdict is Verdict.CANNOT_DETERMINE:
        assert c.leaning is Verdict.MISMATCH, "a grey-band signal has a direction"


def test_unreadable_side_has_no_leaning(cfg):
    """Patch 02 §3: nothing obtained means no view. It must project to NEEDS_REVIEW,
    never to a fabricated defect."""
    out = compare_all({}, {}, cfg)
    assert all(c.leaning is None for c in out.values())


# --------------------------------------------------------------------------
# Corpus-level: the 94 txt+txt pairs
# --------------------------------------------------------------------------

PLANTED_WRONG_DOC = {"email_501", "email_502", "email_503", "email_504", "email_505"}


def test_94_txt_pairs_are_all_either_compared_or_explained(run, cfg, inbox):
    """The stage plan says "94 txt+txt pairs produce complete comparisons", but five
    of those 94 are the planted wrong-document files, which must NOT be compared —
    comparing an invoice against an SI fabricates a defect. So the real property is:
    every txt+txt pair yields a FULL comparison set or a halting reason that says
    why, and never a partial set.
    """
    import re
    pat = re.compile(r"email_\d+_(SI|BL)\.txt$")
    txt_pairs = [e["email_id"] for e in inbox.emails()
                 if len(e["attachments"]) == 2
                 and all(pat.search(a) for a in e["attachments"])]
    assert len(txt_pairs) == 94

    partial, unexplained = [], []
    for eid in txt_pairs:
        rec = run["recs"][eid]
        n = len(rec.comparisons)
        if n == len(cfg.fields):
            continue
        if n != 0:
            partial.append((eid, n))
        elif rec.reason is None:
            unexplained.append(eid)

    assert partial == [], f"partial comparison maps: {partial}"
    assert unexplained == [], f"skipped with no reason given: {unexplained}"

    compared = {eid for eid in txt_pairs
                if len(run["recs"][eid].comparisons) == len(cfg.fields)}
    skipped = set(txt_pairs) - compared
    assert skipped <= PLANTED_WRONG_DOC, \
        f"a legitimate txt pair was not compared: {sorted(skipped - PLANTED_WRONG_DOC)}"
    assert len(compared) >= 89, f"only {len(compared)} of 94 txt pairs were compared"


def test_no_partial_field_maps(run, cfg):
    """The failure mode that would justify a separate gate per format."""
    partial = [eid for eid, r in run["recs"].items()
               if r.comparisons and len(r.comparisons) != len(cfg.fields)]
    assert partial == []


def test_report_is_written_and_shows_si_and_bl_side_by_side(cfg, inbox):
    from shipdoc.adapters.report import ReportAdapter
    from shipdoc.pipeline import run_corpus
    text = ReportAdapter().emit(run_corpus(inbox, cfg, llm=None, decisions={}, cache_dir=TEST_CACHE)["records"])
    assert "SI (authoritative)" in text
    assert "DISCREPANCY REPORT" in text
