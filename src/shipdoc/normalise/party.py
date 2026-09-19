"""M09 — splitting a party field into its company name and its address.

Two problems, one cause, one fix.

1. FORMAT ASYMMETRY. The same party is written differently by different formats:
   an .xlsx cell flattens name and address into `ROXCEL TRADING GMBH | OPERNRING 3-5`,
   a .docx table gives only `ROXCEL TRADING GMBH`, and a .txt file wraps the address
   onto indented continuation lines. Comparing whole blocks made the same company
   look different depending on which file it came from.

2. REVIEW ITEM B7. Inside a long name+address block, a changed legal suffix is a few
   characters among two hundred, so `ABC Sdn Bhd` and `ABC Pte Ltd` score high enough
   to pass as a MATCH. They are different legal entities.

The fix is the same for both: compare the NAME strictly and let the address be
advisory. The name is short, so a suffix change is a large fraction of it.
"""
from __future__ import annotations

import re

# Legal-form tokens. Their FORMATTING is normalised (`SDN. BHD.` -> `SDN BHD`) so the
# same suffix written two ways compares equal. Two DIFFERENT suffixes stay different —
# that is the whole point of B7, and there is deliberately no mapping between them.
LEGAL_SUFFIXES = (
    "SDN BHD", "PTE LTD", "PVT LTD", "CO LTD", "PTY LTD", "GMBH", "LLC", "LLP",
    "FZE", "FZCO", "FZ LLC", "BV", "NV", "SA", "SAS", "SRL", "SPA", "AG", "AB",
    "AS", "OY", "PLC", "LTD", "INC", "CORP", "LIMITED", "COMPANY", "KG", "SL",
)

_SEPARATORS = re.compile(r"\n|\s*\|\s*")
_PUNCT = re.compile(r"[.,;:]+")
_WS = re.compile(r"\s+")

# An address line usually starts with a number, a unit/floor marker, a PO box, or a
# postcode. Used only to catch an address that shares ONE line with the name.
_ADDRESS_START = re.compile(
    r"^\s*(?:"
    r"\d+[\s,/-]"                       # "12 Jalan ...", "43-45 Metropolitan Road"
    r"|(?:NO|LOT|UNIT|SUITE|BLOCK|BLK|FLOOR|LEVEL|ROOM|RM)\b"
    r"|#\s*\d"                          # "#21-01"
    r"|P\.?\s*O\.?\s*BOX\b"
    r")", re.IGNORECASE)


def split_party(raw: str) -> tuple[str, str]:
    """(company name, address). Format-independent: splits on a newline or a `|`,
    which covers .txt continuation lines, .xlsx flattened cells and .docx tables
    alike. A .docx value with no address at all yields ("NAME", "")."""
    if not raw:
        return "", ""
    parts = [p.strip() for p in _SEPARATORS.split(raw) if p.strip()]
    if not parts:
        return "", ""

    name, rest = parts[0], parts[1:]

    # The address sometimes rides on the name's own line after a comma —
    # "ACME TRADING SDN BHD, 12 JALAN SULTAN". Cut at the first comma-separated
    # chunk that looks like an address.
    if "," in name:
        chunks = [c.strip() for c in name.split(",")]
        for i in range(1, len(chunks)):
            if _ADDRESS_START.match(chunks[i]):
                rest = [", ".join(chunks[i:])] + rest
                name = ", ".join(chunks[:i])
                break

    return name.strip(), " ".join(rest).strip()


def normalise_party_name(name: str) -> str:
    """Case, punctuation and whitespace normalised; legal suffixes reduced to a
    canonical SPELLING but never to each other.

        'A.B.C. Trading Sdn. Bhd.'  -> 'ABC TRADING SDN BHD'
        'ABC Trading Pte. Ltd.'     -> 'ABC TRADING PTE LTD'      (still different)
    """
    s = (name or "").upper()
    s = s.replace("&", " AND ")
    # Drop dots inside acronyms before general punctuation handling, so `A.B.C.`
    # becomes `ABC` rather than `A B C`.
    s = re.sub(r"\b(?:[A-Z]\.){2,}", lambda m: m.group(0).replace(".", ""), s)
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"[^\w\s/()-]", " ", s)
    s = _WS.sub(" ", s).strip()

    # Canonicalise the suffix's spacing, longest first so `FZ LLC` wins over `LLC`.
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        pattern = r"\b" + r"\s*".join(map(re.escape, suffix.split())) + r"\b\s*$"
        if re.search(pattern, s):
            s = re.sub(pattern, "", s).strip() + " " + suffix
            break
    return _WS.sub(" ", s).strip()
