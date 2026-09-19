"""M07 layer 1 — deterministic, free, runs first.

It PARTITIONS; it does not decide the residue. Zero attachments does not imply
"not a comparison request": an email that asks for a check and forgets the files is
still the comparison category, with `missing_attachment`.

Verified on this corpus: 220 records are gold BL_COMPARISON but only 126 carry
attachments, so roughly 94 comparison requests arrive with nothing attached. This
layer must return None for those, never GENERAL.
"""
from __future__ import annotations

import re
from typing import NamedTuple

from shipdoc.types import Category, Config, Record

ATTACHMENT_RE = re.compile(r"email_(\d+)_(SI|BL)\.(\w+)$", re.IGNORECASE)


class StructuralVerdict(NamedTuple):
    category: str | None
    confidence: float
    evidence: str


def parse_roles(record: Record) -> dict[str, str]:
    """{"SI": path, "BL": path} for whatever parsed. Role collisions are dropped
    here and detected by the caller via the count."""
    roles: dict[str, str] = {}
    for path in record.raw.get("attachments", ()):
        m = ATTACHMENT_RE.search(path.replace("\\", "/").rsplit("/", 1)[-1])
        if m:
            roles.setdefault(m.group(2).upper(), path)
    return roles


def classify_structural(record: Record, cfg: Config) -> StructuralVerdict:
    attachments = record.raw.get("attachments", ()) or ()
    roles = parse_roles(record)

    if len(attachments) >= 2 and {"SI", "BL"} <= set(roles):
        return StructuralVerdict(cfg.comparison_category, 0.99, "si_and_bl_attached")

    if len(attachments) >= 1 and roles:
        # One half of the pair. Still a comparison request — the other file is
        # missing, which is a review reason, not a different category.
        return StructuralVerdict(cfg.comparison_category, 0.95,
                                 f"only_{'_'.join(sorted(roles))}_attached")

    if attachments:
        # Attachments present but none parse as SI/BL. No structural view.
        return StructuralVerdict(None, 0.0, "attachments_unrecognised")

    return StructuralVerdict(None, 0.0, "no_attachments")
