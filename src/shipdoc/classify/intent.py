"""M07 — what an attachment-free comparison request is actually asking for.

A `BL_COMPARISON` email with no attachments is not automatically a mistake. Most of
them are the shipper ASKING for the draft BL to be sent — there is nothing missing and
nothing to review yet. Treating those as `missing_attachment` buries the handful of
genuinely broken records in a queue of routine requests.

Two intents, decided from the BODY only. No email_id appears here — a rule keyed to a
record is memorising, and `tests/property/test_no_answer_key_leak.py` enforces it.
"""
from __future__ import annotations

import re

BODY_CHARS = 1500

# "Please send the draft BL for checking" — the documents do not exist yet. Nothing is
# missing; we are waiting.
_AWAITING = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(send|share|provide|issue|forward|release)\b[^.]{0,40}\bdraft\b",
    r"\bdraft\b[^.]{0,30}\b(bl|b/l|bill of lading)\b[^.]{0,40}\b(for|to)\b[^.]{0,20}"
    r"\b(check|checking|review|confirm|confirmation|approval)\b",
    r"\b(await|awaiting|pending|expect|expecting)\b[^.]{0,30}"
    r"\b(draft|bl|b/l|documents?|docs?)\b",
    r"\b(kindly|please)\b[^.]{0,30}\b(revert|advise)\b[^.]{0,30}\bdraft\b",
    r"\bonce\b[^.]{0,20}\b(ready|available|issued)\b",
    r"\bwhen\b[^.]{0,20}\b(ready|available|issued)\b",
))

# The sender believes documents are present, or wants a comparison done now. If there
# is nothing attached, something genuinely went wrong.
_EXPECTED_PRESENT = tuple(re.compile(p, re.IGNORECASE) for p in (
    # \w* not (ed|ing|ment)? — the latter does not match the PLURAL
    # "attachments", which is exactly how these bodies are written.
    r"\battach\w*\b",
    r"\benclosed\b",
    r"\bherewith\b",
    r"\bas per the\b[^.]{0,20}\b(attached|enclosed)\b",
    r"\b(dropped|uploaded|shared)\b[^.]{0,25}\b(file|doc|folder|drive)\b",
    # "Please compare the SI and draft BL ... and confirm" — a request to do the
    # comparison NOW. If nothing is attached, something went wrong.
    r"\bcompare\b[^.]{0,60}\bconfirm\b",
    r"\bcompare\b[^.]{0,40}\b(si|bl|b/l|bill of lading)\b",
    r"\bmissing\b[^.]{0,25}\b(attachment|file|document|doc)\b",
    r"\bcould not\b[^.]{0,20}\b(open|read|find)\b",
    r"\bdid not\b[^.]{0,20}\b(receive|arrive|come through)\b",
))


# ---------------------------------------------------------------- Phase 10 Fix 3
#
# An explicit instruction IN THE BODY to compare a BL against an SI. The subject line
# cannot overturn this, and this rule reads the body ONLY — deliberately, because the
# failure it fixes is a subject that describes a different matter in the same thread.
#
# email_998's subject is `URGENT: INVOICE DISPUTE & REMITTANCE ADVICE`; its body says
# "Please immediately audit the draft Bill of Lading against our SI". The subject won,
# the record was classified INVOICE_QUERY, and every downstream stage was skipped.
# Real email works the other way round: subjects are stale, bodies are current.
#
# The rule is deliberately NARROW — all three parts must be present:
#   1. a comparison verb
#   2. a bill of lading
#   3. an SI, or the word "against" (which makes it a two-document instruction)
# Two of the three is not enough. "Please check the BL" alone is a request to look at
# one document, which is not this category, and a rule that fired on it would trade a
# recall gain for a precision loss on an axis worth 0.30.
_CMP_VERB = r"(?:compare|cross-?check|reconcile|verify|audit|check|confirm|review)"
_BL_DOC = r"(?:draft\s+)?(?:b/?l\b|bills?\s+of\s+lading\b|bill\s+of\s+lading\b)"
_SI_DOC = r"(?:s/?i\b|shipping\s+instructions?\b|shipping\s+instruction\b|booking\s+note\b)"

_COMPARE_INSTRUCTION = tuple(re.compile(p, re.IGNORECASE) for p in (
    # "audit the draft Bill of Lading against our SI"
    rf"\b{_CMP_VERB}\b[^.]{{0,60}}\b{_BL_DOC}[^.]{{0,40}}\bagainst\b",
    rf"\b{_CMP_VERB}\b[^.]{{0,60}}\b{_BL_DOC}[^.]{{0,60}}\b{_SI_DOC}",
    # "compare our SI against the draft BL" — the other order
    rf"\b{_CMP_VERB}\b[^.]{{0,60}}\b{_SI_DOC}[^.]{{0,60}}\b{_BL_DOC}",
    # "the BL does not match our shipping instruction"
    rf"\b{_BL_DOC}[^.]{{0,50}}\b(?:does\s+not|doesn't|do\s+not|don't)\s+match\b"
    rf"[^.]{{0,40}}\b{_SI_DOC}",
))


def requests_bl_comparison(record) -> bool:
    """True when the BODY explicitly instructs a BL/SI comparison.

    BODY ONLY. Passing the subject in here would reintroduce exactly the failure this
    rule exists to fix, and would also let a forwarded subject chain trigger it.

    Deterministic and inspectable: no model, no threshold, no score. A reviewer who
    disagrees with an outcome can read the four patterns above and see which one
    fired.
    """
    body = (record.raw.get("body") or "")[:BODY_CHARS]
    return any(p.search(body) for p in _COMPARE_INSTRUCTION)


def awaiting_documents(record) -> bool:
    """True when the sender is ASKING for the draft, not supplying it.

    `_EXPECTED_PRESENT` wins on a tie: if the body claims something was attached and
    nothing is there, that is a real problem and belongs in the queue, whatever else
    the email also says.
    """
    raw = record.raw
    text = f"{raw.get('subject') or ''}\n{(raw.get('body') or '')[:BODY_CHARS]}"

    if any(p.search(text) for p in _EXPECTED_PRESENT):
        return False
    return any(p.search(text) for p in _AWAITING)
