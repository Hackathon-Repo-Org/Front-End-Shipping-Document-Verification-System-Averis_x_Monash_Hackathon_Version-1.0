"""M09 — label text to canonical field name, and value extraction.

Three pitfalls drive this module, all verified against the corpus:

P-LONGEST  `Port of Loading:` (x42) and `Port of Loading (POL):` (x35) both occur.
           Matching the shorter first strands `(POL):` in the value.
P-NET      Longest-match points the WRONG way for weight: `GROSS WEIGHT` (x45) and
           `NET WEIGHT` (x5) both contain "WEIGHT", and email_516_SI.txt carries
           both — gross is `N/A`, net is `_______ MTS`. Needs a negative list.
P-CJK      `Gross Weight毛重(KGS):` is a real label on a compared field. Ignoring
           non-ASCII turns a present field into missing_value.
"""
from __future__ import annotations

import re
import unicodedata

from shipdoc.types import Config, FieldSpec

# A value ends at the next recognised label, a blank line, or this many lines —
# whichever comes first. Written down rather than left implicit (M09).
MAX_VALUE_LINES = 3


def strip_non_ascii(text: str) -> str:
    """P-CJK. Normalise then drop non-ASCII, so `Gross Weight毛重(KGS):` reduces to
    `Gross Weight(KGS):` — which is in the synonym map."""
    norm = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in norm if ord(ch) < 128)


def canon_label(text: str) -> str:
    """Case- and space-insensitive label key."""
    return re.sub(r"\s+", " ", strip_non_ascii(text)).strip().lower()


def label_key(text: str) -> str:
    """Canonical form with any trailing colon removed.

    The colon is NOT part of the label. In .txt attachments a label reads
    `Shipper:` , but a PDF form puts the label and its value in separate columns, so
    the line rebuilt from word coordinates reads `Shipper APRIL FINE PAPER TRADING`
    with no colon at all. Requiring one silently matched 1 label per PDF and had
    every PDF pair rejected as wrong_doc_type.
    """
    return canon_label(text).rstrip(":").strip()


def _matcher(key: str) -> re.Pattern:
    """Label at line start, an optional parenthetical, an optional colon, then the
    value. The separator must be a colon or whitespace so `Shipperton` cannot match
    `Shipper`.

    The parenthetical group is what makes the .docx bills of lading work. Their
    labels carry a CJK gloss — `Shipper/Exporter (发货人)`, `GROSS WEIGHT (毛重 KGS)` —
    and `strip_non_ascii` reduces that to `Shipper/Exporter ()` and
    `GROSS WEIGHT ( KGS)`. Without this group the matcher stopped at the label proper
    and the residue led the VALUE: `() | APRIL FINE PAPER TRADING`. That string does
    not occur in the document, so T3 correctly rejected it and every field on all 8
    docx BLs read as absent.

    The residue is not always empty — `( KGS)` is not — so a rule that drops only
    empty parentheses does not cover gross_weight_kg. Consume any parenthetical that
    sits between the label and its separator.

    A parenthetical belonging to the VALUE is unaffected, because it appears AFTER
    the separator: in `Port of Loading: PORT KLANG (WESTPORT)` the colon is matched
    first and `(WESTPORT)` stays in the value.
    """
    return re.compile(rf"^{re.escape(key)}\s*(?:\([^)]*\)\s*)?(?::|\s|$)\s*",
                      re.IGNORECASE)


class LabelIndex:
    """Synonyms across all fields, longest-first, with per-field negative lists."""

    def __init__(self, cfg: Config):
        entries: list[tuple[str, str, re.Pattern]] = []
        self.anti: dict[str, tuple[str, ...]] = {}
        anti_all: list[tuple[str, re.Pattern]] = []
        for name, spec in cfg.fields.items():
            keys = tuple(label_key(a) for a in spec.anti_synonyms)
            self.anti[name] = keys
            anti_all.extend((k, _matcher(k)) for k in keys)
            for syn in spec.synonyms:
                key = label_key(syn)
                entries.append((key, name, _matcher(key)))
        # P-LONGEST: sort by descending key length. Declaration order in the YAML is
        # also longest-first and a test asserts it, but the authority is here.
        entries.sort(key=lambda e: len(e[0]), reverse=True)
        self.entries = entries
        self._anti_all = anti_all

    @staticmethod
    def _flat(line: str) -> str:
        """Non-ASCII stripped and whitespace collapsed. Matching and value extraction
        both happen on this form, so `Gross Weight毛重(KGS): N/A` yields `N/A`."""
        return re.sub(r"\s+", " ", strip_non_ascii(line)).strip()

    def match(self, line: str) -> tuple[str, str, str] | None:
        """Return (field, label_seen, value_on_this_line) or None."""
        flat = self._flat(line)
        if not flat:
            return None

        # P-NET: an anti-synonym wins outright. `NET WEIGHT` must never be taken as
        # gross weight, and it is longer than `GROSS WEIGHT`, so longest-match alone
        # would happily prefer it.
        for _key, pat in self._anti_all:
            if pat.match(flat):
                return None

        for key, field, pat in self.entries:
            m = pat.match(flat)
            if m:
                # xlsx rows and docx table rows are flattened to "label | value", so
                # the separator is stripped here rather than in each handler — one
                # label matcher serves text, PDF, spreadsheet and table alike.
                value = flat[m.end():].strip().lstrip("|").strip()
                return field, flat[:m.end()].strip().rstrip("|").strip(), value
        return None

    def is_any_label(self, line: str) -> bool:
        flat = self._flat(line)
        return (any(pat.match(flat) for _k, _f, pat in self.entries)
                or any(pat.match(flat) for _k, pat in self._anti_all))


def harvest(text: str, index: LabelIndex) -> dict[str, tuple[str, str, int]]:
    """{field: (label_seen, raw_value, line_number)}.

    First occurrence wins; a second occurrence of the same field is reported by the
    caller as an ambiguity (patch 02 §3: two candidate values => leaning MISMATCH).
    """
    out: dict[str, tuple[str, str, int]] = {}
    duplicates: set[str] = set()
    lines = text.splitlines()

    for i, line in enumerate(lines):
        hit = index.match(line)
        if hit is None:
            continue
        field, label_seen, first = hit
        if field in out:
            duplicates.add(field)
            continue

        parts = [first] if first else []
        # Value termination: next recognised label, blank line, or MAX_VALUE_LINES.
        for cont in lines[i + 1: i + 1 + MAX_VALUE_LINES]:
            if not cont.strip() or index.is_any_label(cont):
                break
            if not cont.startswith((" ", "\t")):
                break          # a continuation is indented; a new flush line is not
            parts.append(cont.strip())
        # Joined with a newline, NOT a space: the boundary between the company name
        # and its address is the thing normalise/party.py needs, and flattening it
        # here is what made .txt values incomparable with .docx ones. T3 is unaffected
        # because verify._flat collapses all whitespace on both sides.
        out[field] = (label_seen, "\n".join(p for p in parts if p).strip(), i + 1)

    for field in duplicates:
        label_seen, value, line_no = out[field]
        out[field] = (label_seen, value, -line_no)   # negative line = ambiguous
    return out
