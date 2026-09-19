"""M09 — T3. `FieldValue.raw_text` must appear in `ExtractedDoc.text`.

T3 changed in v2: it verifies EXTRACTION FIDELITY, not source fidelity. For the 22
.xlsx (flattened rows) and multi-column PDFs (rebuilt by y-position) there is no
source text to verify against — the reconstruction IS the canonical form.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def _flat(text: str) -> str:
    return _WS.sub(" ", text or "").strip().casefold()


def appears_in(raw_text: str, doc_text: str) -> bool:
    """Whitespace is normalised on BOTH sides, or a value that wrapped across two
    lines in the source fails verification and escalates a perfectly good field."""
    if not raw_text or not raw_text.strip():
        return True          # nothing to verify; sentinel handling owns the empty case
    return _flat(raw_text) in _flat(doc_text)
