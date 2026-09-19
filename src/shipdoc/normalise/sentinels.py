"""M09 — raw text to None when it is a null placeholder.

v1.0 guarded `None` thoroughly and was emphatic that two missing values must never
compare MATCH. The guard was on the WRONG REPRESENTATION. In this corpus a missing
value is a non-empty string:

    Gross Weight毛重(KGS): N/A
    NET WEIGHT: _______ MTS

Verified: `_______ MTS` x4, `N/A` x2, `TBA` x1. Both sides carrying "N/A" are equal
under `==`, pass verify.py (the string really is in the source), and reach the
comparator as well-formed values.
"""
from __future__ import annotations

import re
from typing import Iterable

# Unit tokens are stripped BEFORE the sentinel test, or `_______ MTS` never matches
# `^_+$` and the placeholder sails through as a real value.
_TRAILING_UNITS = re.compile(
    r"\s*(kgs?|kilograms?|mts?|tons?|tonnes?|lbs?|pcs?|units?|cbm|ctns?)\s*$",
    re.IGNORECASE)


def strip_units(text: str) -> str:
    prev = None
    out = text.strip()
    while out != prev:
        prev = out
        out = _TRAILING_UNITS.sub("", out).strip()
    return out


def compile_sentinels(patterns: Iterable[str]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


def is_sentinel(raw: str, patterns: tuple[re.Pattern, ...]) -> bool:
    """True when the raw value means 'nothing', however it is spelled."""
    if raw is None:
        return True
    candidates = {raw.strip(), strip_units(raw)}
    # also consider the value with internal whitespace collapsed, so "N / A" matches
    candidates.add(re.sub(r"\s+", "", raw.strip()))
    for cand in candidates:
        for pat in patterns:
            if pat.fullmatch(cand):
                return True
    return False
