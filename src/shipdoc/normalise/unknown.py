"""M09b — find lines that are SHAPED like a label but map to no field we know.

Phase 11, detection half. This module proposes nothing and decides nothing; it only
notices. It answers one question per line: *does this look like a field on a shipping
document, and do we already understand it?*

TRIGGER ON STRUCTURE, NOT PROPORTION
------------------------------------
There is no percentage threshold anywhere in here, deliberately. A label that occurs
on one bill of lading is exactly as worth asking a human about as one that occurs on
two hundred — the question costs the same and the answer is permanent. A frequency
threshold would only mean that the first N documents carrying a new label are
silently mis-extracted while the counter warms up, which is the failure Phase 10
Fix 1 was written to stop.

What makes a line a candidate is therefore shape:
  * it ends in a colon, or it occupies the left cell of a table row, AND
  * something follows it — a label with no value is not evidence of a field, AND
  * the label part is short enough to be a label and not a sentence, AND
  * no known synonym or anti-synonym already matches it.

Free text, headers, addresses and footer boilerplate fail the first or third test:
prose has no colon in label position, addresses wrap without one, and a heading has
nothing after it.
"""
from __future__ import annotations

import re

from shipdoc.normalise.labels import LabelIndex, label_key, strip_non_ascii
from shipdoc.types import UnknownLabel

# A label is short. Five words is generous for `No. of Containers or Packages` and
# still refuses `we noticed a critical issue on the draft BL and would like you to`.
MAX_LABEL_WORDS = 6
MAX_LABEL_CHARS = 44
MIN_LABEL_CHARS = 3

# A value that runs on for a paragraph means the colon was punctuation inside prose,
# not a field separator.
MAX_VALUE_CHARS = 160

CONTEXT_LINES = 2

# Sentence-ish punctuation inside the label half: prose, not a field name.
_PROSE = re.compile(r"[.!?;]\s|\S,\s\S|\b(?:we|you|please|kindly|the|this|that|and|"
                    r"for|with|from|have|has|will|would|our)\b\s+\b(?:are|is|was|"
                    r"were|have|has|will|would|can|could|should)\b", re.IGNORECASE)

# Document furniture. These end in a colon and take a value, but they are not fields
# on a shipping document and a reviewer should not be asked about them every time a
# new carrier's template appears.
_BOILERPLATE = re.compile(
    r"^(?:date|dated|ref|reference|our ref|your ref|page|sheet|tel|telephone|fax|"
    r"email|e-mail|website|attn|attention|subject|subj|re|from|to|cc|bcc|sent|"
    r"signature|signed|authorised signatory|authorized signatory|for and on behalf|"
    r"remarks?|notes?|terms?|conditions?|disclaimer|copyright|printed|prepared by)$",
    re.IGNORECASE)


def _split_candidate(line: str) -> tuple[str, str] | None:
    """Return (label_part, value_part) for a line shaped like a field, else None."""
    flat = re.sub(r"\s+", " ", strip_non_ascii(line)).strip()
    if not flat:
        return None

    # Table rows (docx/xlsx) are flattened to `label | value` upstream, so the left
    # cell is the label whether or not anyone typed a colon.
    if "|" in flat:
        left, _, right = flat.partition("|")
        return left.strip().rstrip(":").strip(), right.strip()

    if ":" not in flat:
        return None
    left, _, right = flat.partition(":")
    return left.strip(), right.strip()


def is_candidate(line: str) -> tuple[str, str] | None:
    """Shape test only. Knows nothing about which fields exist."""
    parts = _split_candidate(line)
    if parts is None:
        return None
    label, value = parts

    if not (MIN_LABEL_CHARS <= len(label) <= MAX_LABEL_CHARS):
        return None
    if len(label.split()) > MAX_LABEL_WORDS:
        return None
    if not value or len(value) > MAX_VALUE_CHARS:
        return None                       # a heading, or a colon inside prose
    if len(re.findall(r"[A-Za-z]", label)) < 3:
        return None                       # not a name; a code or a number
    if label[0].isdigit():
        return None
    if _PROSE.search(label):
        return None
    if _BOILERPLATE.match(label.strip().rstrip(":").strip()):
        return None
    return label, value


def find_unknown(text: str, index: LabelIndex, ref: str, role: str,
                 ) -> list[UnknownLabel]:
    """Every label-shaped line in `text` that the index does not already recognise.

    Anti-synonyms count as recognised: `NET WEIGHT` is not an unknown label, it is a
    known one we have deliberately decided to refuse, and surfacing it as a
    discovery would be a bug.
    """
    lines = text.splitlines()
    out: list[UnknownLabel] = []
    seen: set[str] = set()

    for i, line in enumerate(lines):
        if index.match(line) is not None or index.is_any_label(line):
            continue
        parts = is_candidate(line)
        if parts is None:
            continue
        label, value = parts
        key = label_key(label)
        if not key or key in seen:
            continue
        seen.add(key)

        lo = max(0, i - CONTEXT_LINES)
        hi = min(len(lines), i + CONTEXT_LINES + 1)
        out.append(UnknownLabel(
            raw=label, normalised=key, value=value, doc_ref=ref, line_no=i + 1,
            role=role, context="\n".join(lines[lo:hi]).strip(),
        ))
    return out
