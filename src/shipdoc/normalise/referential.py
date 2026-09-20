"""M09 — referential field values.

`NOTIFY PARTY: SAME AS CONSIGNEE` is not a company called "Same As Consignee". It is
a pointer to another field on the SAME document, and it is ordinary practice: a
notify party is identical to the consignee often enough that typing it twice is the
exception. Comparing the pointer as a literal name manufactures a defect on a pair of
documents that agree.

The forms below come from what freight documents actually contain, not from what
email_997 happened to use. Ditto marks in particular are a paper-form convention that
survives into typed documents: `DO.`, `-do-`, a bare quotation mark in a column.

WHAT THIS MODULE DELIBERATELY WILL NOT DO
-----------------------------------------
Resolve across documents. A BL that says `SAME AS CONSIGNEE` means the consignee on
THAT BILL OF LADING. Resolving it against the SI's consignee would compare the SI to
itself and report `match` on every such field — the comparison would be structurally
incapable of finding a defect, which is worse than the false positive it replaces.

Every failure mode here resolves to CANNOT_DETERMINE rather than to a guess:

  target field not present on this document  -> unresolved
  target is itself a reference that dead-ends -> unresolved
  reference cycle (A -> B -> A)               -> unresolved
  `SAME AS ABOVE` with nothing above it       -> unresolved

"Unresolved" is not a defect. It means the document points somewhere we could not
follow, and a human should look.
"""
from __future__ import annotations

import re

# `SAME AS <field>`, `AS PER <field>`, `REFER TO <field>`, `SEE <field>`.
# The target is captured loosely — it is matched against the label index afterwards,
# so being generous here costs nothing and being strict loses real forms.
_NAMED = re.compile(
    r"^(?:same\s+as|as\s+per|as\s+in|refer\s+to|see|per)\s+(?P<target>[a-z0-9 ./&()'-]{2,40}?)"
    r"\s*\.?$",
    re.IGNORECASE,
)

# Ditto: the value repeats whatever sits immediately above it.
_DITTO = re.compile(r"""^(?:-?\s*do\s*-?\.?|["'″”]|,,|''|--)$""", re.IGNORECASE)

# Words that mean "the entry above" rather than naming a field.
_ABOVE = frozenset({"above", "the above", "above mentioned", "abovementioned",
                    "aforementioned", "previous", "preceding"})

MAX_HOPS = 8


def classify_reference(raw: str) -> tuple[str, str | None] | None:
    """Return (kind, target_text) or None if `raw` is an ordinary value.

    kind is "named" (target_text names a field), or "above" / "ditto" (target_text is
    None and the caller resolves positionally).
    """
    if not raw:
        return None
    # Only the first line: `SAME AS CONSIGNEE` followed by an address continuation is
    # not a pure reference, and substituting a value would discard the address.
    text = raw.strip().splitlines()[0].strip() if raw.strip() else ""
    flat = re.sub(r"\s+", " ", text).strip().strip(".,;:").strip()
    if not flat:
        return None
    if _DITTO.match(flat):
        return "ditto", None
    m = _NAMED.match(flat)
    if m is None:
        return None
    target = re.sub(r"\s+", " ", m.group("target")).strip().strip(".,;:").strip()
    if target.lower() in _ABOVE:
        return "above", None
    return "named", target


def target_field(target_text: str, label_to_field: dict[str, str]) -> str | None:
    """Map `CONSIGNEE` / `the consignee` / `Consignee (Receiver)` to a field name.

    Uses the SAME label vocabulary the extractor matches on, so a synonym that is
    good enough to label a field is good enough to point at one. Adding a synonym
    therefore improves both halves at once.
    """
    key = re.sub(r"\s+", " ", target_text).strip().lower().rstrip(":").strip()
    key = re.sub(r"^(?:the|our|your)\s+", "", key).strip()
    if key in label_to_field:
        return label_to_field[key]
    # A trailing parenthetical gloss, e.g. `CONSIGNEE (RECEIVER)`.
    bare = re.sub(r"\s*\([^)]*\)\s*$", "", key).strip()
    if bare in label_to_field:
        return label_to_field[bare]
    # Last resort: the longest label key that the target CONTAINS as a whole phrase.
    best: str | None = None
    for lk, fname in label_to_field.items():
        if len(lk) < 4:
            continue
        if re.search(rf"\b{re.escape(lk)}\b", bare or key):
            if best is None or len(lk) > len(best):
                best, field = lk, fname
    return label_to_field[best] if best else None
