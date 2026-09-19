"""M14 — the ONLY translation from the internal reason vocabulary to the external one.

Deliberately not 1:1: two distinct internal causes both surface as `missing_value`,
which is what makes this a real boundary rather than an identity function.
"""
from __future__ import annotations

from shipdoc.types import ReasonKey

REVIEW_REASON: dict[ReasonKey, str] = {
    ReasonKey.ERR_NO_ATTACHMENT: "missing_attachment",
    ReasonKey.ERR_BAD_DOC_TYPE:  "wrong_doc_type",
    ReasonKey.ERR_UNREADABLE:    "unreadable",
    ReasonKey.ERR_NO_VALUE:      "missing_value",
    ReasonKey.ERR_CLASSIFY:      "missing_value",
    ReasonKey.ERR_UNHANDLED:     "unreadable",
}

assert set(REVIEW_REASON) == set(ReasonKey), (
    "every internal reason key must have an external spelling, or a record escalates "
    "with a reason the submission cannot express"
)
