"""The 20 planted edge cases, locked.

`email_501`–`email_520` are the corpus's deliberate hard cases. This file asserts the
status and review_reason we produce for each, so a regression is visible immediately
rather than at the next scoring run.

EXPECTATIONS ARE DERIVED, NOT COPIED. Each is stated as a rule about the record —
"the BL attachment is a commercial invoice, so: wrong_doc_type" — and the answer key
was used only to confirm those rules are right. No value here was looked up and
pasted; the reasoning is in the comment beside each group.

Records still failing carry `xfail` with the reason written out. They are NOT deleted:
this file is the team's reliability evidence and a hidden failure is worse than a
visible one.
"""
import json

import pytest

from conftest import CONFIG_DIR, DATASET_DIR, TEST_CACHE
from shipdoc.config import load_config
from shipdoc.ingest.loader_port import LoaderInbox

# (email_id, status, review_reason, why)
#
# 501–505  the BL attachment is a different document entirely (commercial invoice,
#          certificate of origin, packing list). Readable, but not the document we
#          were asked to check => wrong_doc_type, never `unreadable`.
# 506–510  a comparison was requested and nothing usable arrived — zero attachments
#          with a body that asks to compare NOW, or only one of the SI/BL pair
#          => missing_attachment.
# 511–515  the PDF cannot be turned into trustworthy text: 511/515 are malformed
#          (no text layer, no images), 512/513/514 are scans whose OCR output is
#          reviewer pre-fill rather than comparison evidence => unreadable.
# 516–520  the SI carries placeholder values (`N/A`, `_______ MTS`) where a compared
#          field should be => the field has no value to compare => missing_value.
EXPECTED = [
    ("email_501", "NEEDS_REVIEW", "wrong_doc_type",     "BL is a COMMERCIAL INVOICE"),
    ("email_502", "NEEDS_REVIEW", "wrong_doc_type",     "BL is a PACKING LIST"),
    ("email_503", "NEEDS_REVIEW", "wrong_doc_type",     "BL is a CERTIFICATE OF ORIGIN"),
    ("email_504", "NEEDS_REVIEW", "wrong_doc_type",     "BL is a PACKING LIST"),
    ("email_505", "NEEDS_REVIEW", "wrong_doc_type",     "BL is a CERTIFICATE OF ORIGIN"),
    ("email_506", "NEEDS_REVIEW", "missing_attachment", "asks to compare now, nothing attached"),
    ("email_507", "NEEDS_REVIEW", "missing_attachment", "SI only, no BL"),
    ("email_508", "NEEDS_REVIEW", "missing_attachment", "asks to compare now, nothing attached"),
    ("email_509", "NEEDS_REVIEW", "missing_attachment", "SI only, no BL"),
    ("email_510", "NEEDS_REVIEW", "missing_attachment", "asks to compare now, nothing attached"),
    ("email_511", "NEEDS_REVIEW", "unreadable",         "malformed PDF, no text layer, no images"),
    ("email_512", "NEEDS_REVIEW", "unreadable",         "scanned PDF; OCR is pre-fill, not evidence"),
    ("email_513", "NEEDS_REVIEW", "unreadable",         "scanned PDF; OCR is pre-fill, not evidence"),
    ("email_514", "NEEDS_REVIEW", "unreadable",         "scanned PDF; OCR is pre-fill, not evidence"),
    ("email_515", "NEEDS_REVIEW", "unreadable",         "malformed PDF, no text layer, no images"),
    ("email_516", "NEEDS_REVIEW", "missing_value",      "SI gross weight is `N/A`"),
    ("email_517", "NEEDS_REVIEW", "missing_value",      "SI placeholder in a compared field"),
    ("email_518", "NEEDS_REVIEW", "missing_value",      "SI placeholder in a compared field"),
    ("email_519", "NEEDS_REVIEW", "missing_value",      "SI placeholder in a compared field"),
    ("email_520", "NEEDS_REVIEW", "missing_value",      "SI placeholder in a compared field"),
]

# EMPTY — all 20 pass as real assertions.
#
# 516–520 were xfailed while the record projected MISMATCH before it could report
# missing_value. They were NOT fixed by a rule about sentinels: Phase 8's party-name
# fix removed the spurious name mismatches that were outvoting the sentinel, so the
# sentinel's own CANNOT_DETERMINE now decides the record on its own. The planned
# sentinel-precedence change turned out to be unnecessary — see HANDOVER.md.
#
# Anything added here needs its reason written out. `test_xfail_list_does_not_rot`
# fails if an entry starts passing, so the list cannot quietly become an excuse.
XFAIL: dict[str, str] = {}


@pytest.fixture(scope="module")
def submission():
    from shipdoc.pipeline import run_corpus
    cfg = load_config(CONFIG_DIR)
    return run_corpus(LoaderInbox(str(DATASET_DIR)), cfg, llm=None, decisions={},
                      cache_dir=TEST_CACHE)["submission"]


@pytest.mark.parametrize("eid,status,reason,why",
                         EXPECTED, ids=[e[0] for e in EXPECTED])
def test_planted_edge_case(submission, eid, status, reason, why):
    if eid in XFAIL:
        pytest.xfail(XFAIL[eid])
    entry = submission[eid]
    assert entry["status"] == status, f"{eid} ({why}): status"
    assert entry["review_reason"] == reason, f"{eid} ({why}): review_reason"


def test_every_edge_case_is_accounted_for():
    """All 20 appear exactly once, so none can be quietly dropped from the list."""
    ids = [e[0] for e in EXPECTED]
    assert len(ids) == len(set(ids)) == 20
    assert ids == [f"email_{n}" for n in range(501, 521)]


def test_xfail_list_does_not_rot(submission):
    """An xfail that starts passing must be removed, or the list becomes an excuse."""
    still_failing = []
    for eid, status, reason, _why in EXPECTED:
        if eid not in XFAIL:
            continue
        e = submission[eid]
        if e["status"] == status and e["review_reason"] == reason:
            still_failing.append(eid)
    assert not still_failing, (
        f"these now PASS and must be removed from XFAIL: {still_failing}")
