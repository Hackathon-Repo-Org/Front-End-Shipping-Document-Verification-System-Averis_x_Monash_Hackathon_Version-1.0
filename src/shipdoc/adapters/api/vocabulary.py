"""M18a — the external vocabulary, served to the UI. Phase 14.

THE FRONTEND MUST NOT HARDCODE THESE STRINGS.

`adapters/` owns the external spellings — that boundary is why
`adapters/reason_map.py` performs a real translation from the internal `ReasonKey`
vocabulary instead of being an identity function wearing a boundary's clothes. A
category name pasted into a React component re-implements that mapping in a second
place, in a different language, with nothing checking the two agree. The rename that
follows breaks the UI silently: no error, just a filter that quietly matches nothing.

So the UI asks. Everything it needs to render a dropdown, a badge or a column header
comes from `GET /api/vocabulary`, in display order, with labels and colours attached.

Display order is meaningful and is decided here, not in CSS:
  * statuses run OK -> MISMATCH -> NEEDS_REVIEW, worst last, because that is the
    order a reviewer scans a list in
  * fields run in the order they appear on a bill of lading, so the detail screen
    reads like the document it is checking
"""
from __future__ import annotations

from shipdoc.types import Category, RecordState, Verdict

# Status: the three external values in `submission.json`.
STATUSES = [
    {"value": "OK", "label": "OK", "tone": "success",
     "icon": "check-circle-fill",
     "help": "Compared, and the documents agree."},
    {"value": "MISMATCH", "label": "Mismatch", "tone": "danger",
     "icon": "exclamation-octagon-fill",
     "help": "A confirmed discrepancy between the SI and the draft BL."},
    {"value": "NEEDS_REVIEW", "label": "Needs review", "tone": "warning",
     "icon": "question-circle-fill",
     "help": "The system could not decide. A human has to look."},
]

CATEGORIES = [
    {"value": "BL_COMPARISON", "label": "BL comparison", "tone": "primary",
     "help": "Asks for a draft BL to be checked against the SI."},
    {"value": "SI_REQUEST", "label": "SI request", "tone": "muted",
     "help": "Sends or asks for a shipping instruction."},
    {"value": "INVOICE_QUERY", "label": "Invoice query", "tone": "muted",
     "help": "About billing, not documents."},
    {"value": "GENERAL", "label": "General", "tone": "muted",
     "help": "Correspondence with no document action."},
    {"value": "SPAM", "label": "Spam", "tone": "muted", "help": "Not shipping."},
]

# The EXTERNAL review reasons, as they appear in the submission — deliberately not
# the internal ReasonKey spellings.
REVIEW_REASONS = [
    {"value": "missing_attachment", "label": "Missing attachment",
     "help": "A comparison was asked for and nothing was attached."},
    {"value": "wrong_doc_type", "label": "Wrong document type",
     "help": "The attachment is not the document it claims to be."},
    {"value": "unreadable", "label": "Unreadable",
     "help": "The file could not be read, or is a scan with OCR off."},
    {"value": "missing_value", "label": "Missing value",
     "help": "A compared field had no usable value on one side."},
]

VERDICTS = [
    {"value": "MATCH", "label": "Match", "tone": "success",
     "icon": "check-circle-fill"},
    {"value": "MISMATCH", "label": "Mismatch", "tone": "danger",
     "icon": "x-octagon-fill"},
    {"value": "CANNOT_DETERMINE", "label": "Cannot determine", "tone": "warning",
     "icon": "question-circle-fill"},
]

DECISION_TYPES = [
    {"value": "confirm", "label": "Confirm", "key": "A",
     "help": "Agree with what the system found."},
    {"value": "correct_value", "label": "Correct value", "key": "C",
     "help": "Replace a field value with the right one."},
    {"value": "override_category", "label": "Override category", "key": "O",
     "help": "The email was filed under the wrong category."},
    {"value": "clear_escalation", "label": "Clear escalation", "key": "E",
     "help": "Resolve a record-level escalation. May bypass the state rule."},
    {"value": "retry", "label": "Retry", "key": "R",
     "help": "Process this record again."},
]


def field_order(cfg) -> list[dict]:
    """The seven compared fields, in the order they appear on a bill of lading.

    Read from the CONFIG rather than listed here, so adding a compared field to
    `fields.yaml` shows up in the UI without a second edit. `fields.yaml` preserves
    declaration order, which is already document order.
    """
    pretty = {
        "shipper": "Shipper",
        "consignee": "Consignee",
        "notify_party": "Notify party",
        "port_of_loading": "Port of loading",
        "port_of_discharge": "Port of discharge",
        "container_count": "Containers",
        "gross_weight_kg": "Gross weight (kg)",
    }
    return [{"value": name,
             "label": pretty.get(name, name.replace("_", " ").capitalize()),
             "type": spec.type,
             "address_bearing": bool(spec.address_bearing)}
            for name, spec in cfg.fields.items()]


def build(cfg) -> dict:
    """Everything the UI needs to render without inventing a single string."""
    return {
        "statuses": STATUSES,
        "categories": CATEGORIES,
        "review_reasons": REVIEW_REASONS,
        "verdicts": VERDICTS,
        "decision_types": DECISION_TYPES,
        "fields": field_order(cfg),
        "comparison_category": cfg.comparison_category,
        # Asserted against the enums so this file cannot drift from types.py
        # without a test noticing.
        "_enums": {
            "category": [c.value for c in Category],
            "verdict": [v.value for v in Verdict],
            "state": [s.value for s in RecordState],
        },
    }
