"""M08 step 1 — runs BEFORE extraction. Cheap: no extraction needed to know a
record has only one attachment.
"""
from __future__ import annotations

import re

from shipdoc.errors import DocumentTypeError, MissingAttachmentError
from shipdoc.types import Record

ATTACHMENT_RE = re.compile(r"^email_(\d+)_(SI|BL)\.(\w+)$", re.IGNORECASE)


def route_by_name(record: Record) -> dict[str, str]:
    """{"SI": path, "BL": path}. Raises MissingAttachmentError / DocumentTypeError.

    Filename anchoring (spec Open Item 6, decided here): the pattern is anchored at
    BOTH ends of the stem, so `email_012_BL_final.txt` does NOT match as `_BL`. A
    variant spelling is a routing question for a human, not something to guess at.
    0 exceptions across the 250 files in this corpus.
    """
    attachments = list(record.raw.get("attachments") or ())
    if not attachments:
        raise MissingAttachmentError(f"{record.email_id}: no attachments")

    want = record.email_id.split("_")[-1]
    roles: dict[str, str] = {}
    unparsed: list[str] = []

    for path in attachments:
        base = path.replace("\\", "/").rsplit("/", 1)[-1]
        m = ATTACHMENT_RE.match(base)
        if not m:
            unparsed.append(base)
            continue
        number, role = m.group(1), m.group(2).upper()
        # Bind the filename's number to the record. v1.0 captured it and threw it
        # away; a cross-linked attachment would compare the wrong pair of documents,
        # confidently. 0 instances here — a one-line guard on a silent catastrophe.
        if number.lstrip("0") != want.lstrip("0"):
            raise DocumentTypeError(
                f"{record.email_id}: attachment {base} belongs to email_{number}")
        # Two attachments can collide on the dict key (email_012_BL.txt +
        # email_012_BL_v2.txt). Without this, one vanishes and the KeyError that
        # follows is reported as the wrong reason.
        if role in roles:
            raise DocumentTypeError(
                f"{record.email_id}: two attachments both parse as {role}")
        roles[role] = path

    if unparsed:
        raise DocumentTypeError(
            f"{record.email_id}: unrecognised attachment name(s): {unparsed}")

    missing = {"SI", "BL"} - set(roles)
    if missing:
        raise MissingAttachmentError(
            f"{record.email_id}: missing {sorted(missing)}; have {sorted(roles)}")

    return roles
