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
