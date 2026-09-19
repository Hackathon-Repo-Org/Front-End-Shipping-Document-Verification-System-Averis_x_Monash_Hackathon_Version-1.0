"""M08 step 2 — runs AFTER extraction, and owns the "is this the right kind of
document" question.

This check lived in `extract/` in v1.0 and it was wrong there, verifiably:
`email_501_BL.txt` is a COMMERCIAL INVOICE — perfectly readable, zero shipping
labels — so v1.0 declared it `unreadable` and the router's wrong_doc_type check never
ran. `extract/` has no field registry and should not have one; this module does.
"""
from __future__ import annotations

from typing import Protocol

from shipdoc.errors import DocumentTypeError, ExtractionError
from shipdoc.types import Config, ExtractedDoc, Method


class LabelMatcher(Protocol):
    """What this module needs from a label index, declared here rather than imported.

    v2 §3 places `normalise` above `route`, so importing its LabelIndex — even under
    TYPE_CHECKING — would be a leftward import. Stating the requirement locally
    inverts the dependency: route says what it needs, and normalise happens to
    satisfy it. The caller supplies the instance.
    """

    def match(self, line: str) -> tuple[str, str, str] | None: ...


_SI_TITLES = ("shipping instruction", "shipping instructions", "booking confirmation")
_BL_TITLES = ("bill of lading", "b/l", "waybill", "sea waybill")

# Titles that positively identify a document as something we were NOT sent to compare.
# All five planted wrong-document files declare themselves in their first line.
_OTHER_TITLES = (
    "commercial invoice", "proforma invoice", "tax invoice",
    "certificate of origin", "packing list", "weight list",
    "delivery order", "arrival notice", "debit note", "credit note",
)


def space_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for c in text if c.isspace()) / len(text)


def count_labels(doc: ExtractedDoc, index: LabelMatcher) -> int:
    return sum(1 for line in doc.text.splitlines() if index.match(line) is not None)


def confirm_doc_type(docs: dict[str, ExtractedDoc], cfg: Config,
                     index: LabelMatcher) -> None:
    """Raises DocumentTypeError (wrong_doc_type) or ExtractionError (unreadable).

    `index` is REQUIRED. It used to default to a freshly built LabelIndex(cfg), which
    forced this module to import from `normalise` — a leftward import the layering
    test now forbids. The orchestrator owns construction.
    """
    for role, doc in docs.items():
        if not doc.ok:
            raise ExtractionError(f"{role}: {doc.failure}")

        # SCAN POLICY (review item B2). OCR output is reviewer PRE-FILL, not evidence
        # for an automated comparison. A scanned page read at ~270 characters cannot
        # support a confident MATCH or MISMATCH on seven fields, and committing to one
        # on that basis is exactly the confident-wrong-answer this system exists to
        # avoid. The text stays on `rec.documents` so the review queue can show it and
        # a human can correct it in one pass; the RECORD reports unreadable.
        if doc.method is Method.OCR:
            raise ExtractionError(
                f"{role}: read by OCR ({len(doc.text)} chars) — kept as reviewer "
                f"pre-fill, not used as comparison evidence")

        # A POSITIVE identification of some other document type settles it outright,
        # before any label count. All five planted wrong-document files carry enough
        # shipping labels to clear min_labels_present (a PACKING LIST and a
        # CERTIFICATE OF ORIGIN both name a shipper and a consignee), so counting
        # labels alone lets four of the five through to be compared — which fabricates
        # a defect rather than reporting the real problem.
        other = _other_kind(doc)
        if other is not None:
            raise DocumentTypeError(
                f"{role} attachment is a {other}, not a shipping document")

        n = count_labels(doc, index)
        if n >= cfg.thresholds.min_labels_present:
            continue

        # Too few shipping labels. Two very different causes, and they map to
        # different review reasons.
        if doc.method is Method.PDF_TEXT and \
                space_ratio(doc.text) < cfg.thresholds.pdf_space_ratio_min:
            # A text layer that extracts as SHIPPERGLOBALRUBBER — the document may
            # well be the right kind, we simply cannot read it.
            raise ExtractionError(
                f"{role}: broken PDF text layer (space ratio "
                f"{space_ratio(doc.text):.3f} < {cfg.thresholds.pdf_space_ratio_min})")
        raise DocumentTypeError(
            f"{role}: readable but only {n} shipping label(s) found — "
            f"first line {doc.text.splitlines()[0][:60]!r}"
            if doc.text.strip() else f"{role}: no recognisable shipping labels")

    # If both documents look like the same type, escalate — do not pick one.
    # Guessing inverts the reference direction and the system then confidently
    # reports that the customer's own SI needs correcting.
    kinds = {role: _title_kind(doc) for role, doc in docs.items()}
    known = {r: k for r, k in kinds.items() if k is not None}
    if len(known) == 2 and len(set(known.values())) == 1:
        raise DocumentTypeError(
            f"both attachments look like a {next(iter(known.values()))}")
    for role, kind in known.items():
        if kind is not None and kind != role:
            raise DocumentTypeError(
                f"{role} attachment reads as a {kind} document")


def _head(doc: ExtractedDoc) -> str:
    return "\n".join(doc.text.splitlines()[:3]).lower()


def _title_kind(doc: ExtractedDoc) -> str | None:
    head = _head(doc)
    # "INSTRUCTION" settles it before any BL check. The PDF shipping instructions in
    # this corpus are titled `BILL OF LADING INSTRUCTION` — which contains
    # "bill of lading", so checking BL first reads every PDF SI as a BL and then
    # escalates the pair as "both look like a BL".
    if "instruction" in head:
        return "SI"
    if any(t in head for t in _SI_TITLES):
        return "SI"
    if any(t in head for t in _BL_TITLES):
        return "BL"
    return None


def _other_kind(doc: ExtractedDoc) -> str | None:
    """A document that names itself as a different artifact entirely."""
    head = _head(doc)
    for title in _OTHER_TITLES:
        if title in head:
            return title
    return None
