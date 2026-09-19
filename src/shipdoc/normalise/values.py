"""M09 — raw value to typed normalised value.

A parse failure must NOT bubble as an exception: that is the difference between
FAILED and CANNOT_DETERMINE, and v1.0 left it unstated. Everything here returns
None on failure.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from shipdoc.types import FieldSpec

_WS = re.compile(r"\s+")
_NUM = re.compile(r"[-+]?[\d,. ']+")
_SIZE_TOKEN = re.compile(r"\d{2}\s*'?\s*(?:HC|GP|FCL|RF|OT|FR|DV|TK)\b", re.IGNORECASE)


def normalise_text(raw: str) -> str:
    """Case and punctuation only. Company suffixes are NOT stripped: `ABC Sdn Bhd`
    and `ABC Pte Ltd` are different legal entities."""
    s = _WS.sub(" ", raw or "").strip().upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"[.,;:]+", " ", s)
    s = re.sub(r"[^\w\s/()-]", " ", s)
    return _WS.sub(" ", s).strip()


def parse_decimal(token: str) -> Decimal | None:
    """Thousands vs decimal separator is genuinely ambiguous (`1,234`).

    Rule, recorded in Comparison.detail so a reviewer can see what was assumed:
      - more than one comma group, or a comma followed by exactly 3 digits that is
        not the only group => thousands separator
      - a single separator followed by 1-2 digits, or by 4+ => decimal point
    """
    if token is None:
        return None
    t = token.strip().replace(" ", "").replace("'", "").replace(" ", "")
    if not t:
        return None
    if "," in t and "." in t:
        # whichever comes last is the decimal point
        t = (t.replace(",", "") if t.rfind(".") > t.rfind(",")
             else t.replace(".", "").replace(",", "."))
    elif "," in t:
        groups = t.split(",")
        tail = groups[-1]
        t = t.replace(",", "") if (len(groups) > 2 or len(tail) == 3) else t.replace(",", ".")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def parse_quantity(raw: str, spec: FieldSpec) -> tuple[Decimal | None, str]:
    """Convert to the field's base unit. Unrecognised unit => None => the comparator
    reports CANNOT_DETERMINE. MT / T / TON are NOT synonyms and the conversions come
    from config, never from a guess here."""
    if not raw:
        return None, "empty"
    text = raw.strip()
    m = _NUM.search(text)
    if not m:
        return None, "no_number"
    value = parse_decimal(m.group(0))
    if value is None:
        return None, "unparseable_number"

    unit_text = text[m.end():].strip().upper()
    unit_token = re.sub(r"[^A-Z]", "", unit_text)
    base = (spec.unit or "").upper()

    if not unit_token or unit_token in (base, base + "S", "KG", "KGS"):
        return value, f"{value} (assumed {base or 'base'})"
    for name, factor in spec.conversions.items():
        if unit_token in (name.upper(), name.upper() + "S"):
            return value * Decimal(factor), f"{value} {unit_token} -> {value * Decimal(factor)} {base}"
    return None, f"unrecognised_unit:{unit_token}"


def parse_container_count(raw: str, spec: FieldSpec) -> tuple[int | None, str]:
    """Extract the COUNT, not the size. `1 x 40'HC` -> 1; `40` is the size.

    P-MULTISIZE: `2 x 40'HC + 1 x 20'GP` has no integer representation — summing
    gives 3, which compares MATCH against `3 x 40'HC`, a different shipment. Any
    `+` or a second size token => None => CANNOT_DETERMINE, never a silent sum.
    """
    if not raw:
        return None, "empty"
    text = raw.strip()
    if "+" in text or len(_SIZE_TOKEN.findall(text)) > 1:
        return None, "multi_size_shipment"
    if spec.extract_pattern:
        m = re.search(spec.extract_pattern, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1)), f"pattern -> {m.group(1)}"
            except ValueError:
                return None, "pattern_group_not_an_int"
    m = re.search(r"\b(\d+)\b", text)
    if not m:
        return None, "no_integer"
    return int(m.group(1)), f"first_integer -> {m.group(1)}"
