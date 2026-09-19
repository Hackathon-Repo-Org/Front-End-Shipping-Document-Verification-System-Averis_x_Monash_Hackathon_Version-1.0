"""M09 — port string to a comparable identity, via UN/LOCODE.

A regex recognises the SHAPE `^[A-Z]{2}[A-Z0-9]{3}$`; it cannot tell you that CNSHA
is Shanghai. That needs the reference table, which ships at `config/unlocode.csv.gz`
(see `config/REFERENCE_DATA.md` for provenance).

THE RULE THIS MODULE EXISTS TO OBEY: `resolve()` returns None when it cannot
resolve. It never falls back to echoing its input. A fallback like
`TABLE.get(cleaned, cleaned)` means two unresolvable values get string-compared and
can produce a confident MATCH or MISMATCH out of nothing — the exact silent-pass
class this whole architecture is built to prevent.

NO FUZZY MATCHING INTO THE TABLE. 116k rows plus fuzzy matching produces confident
garbage: "Santa Cruz" matches something, somewhere, in every country on earth.
Resolution is exact-match on a normalised key, or it is nothing. RapidFuzz stays in
the field-level name comparator and does not touch this lookup.
"""
from __future__ import annotations

import csv
import gzip
import io
import re
from pathlib import Path

from shipdoc.normalise.values import normalise_text

LOCODE_SHAPE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}$")
_TOKEN = re.compile(r"\b[A-Z0-9]{5}\b")

# Stripped from the front of a location name before lookup. UN/LOCODE stores
# "Klang" and the documents say "Port of Klang" / "PORT KLANG".
_NAME_PREFIXES = ("PORT OF ", "PORT ", "PUERTO DE ", "PUERTO ", "PORTO DI ", "PORTO ")

# Country words that may appear alongside a port name in one field. Used ONLY to
# disambiguate a name that maps to more than one LOCODE — never to guess.
COUNTRY_WORDS = {
    "MALAYSIA": "MY", "SINGAPORE": "SG", "INDIA": "IN", "CHINA": "CN",
    "PERU": "PE", "JORDAN": "JO", "POLAND": "PL", "GUINEA": "GN",
    "TURKEY": "TR", "TURKIYE": "TR", "SLOVENIA": "SI", "CHILE": "CL",
    "KOREA": "KR", "SOUTH KOREA": "KR", "ISRAEL": "IL", "VIETNAM": "VN",
    "INDONESIA": "ID", "THAILAND": "TH", "FRANCE": "FR", "SPAIN": "ES",
    "ITALY": "IT", "GERMANY": "DE", "NETHERLANDS": "NL", "BELGIUM": "BE",
    "JAPAN": "JP", "TAIWAN": "TW", "PHILIPPINES": "PH", "BANGLADESH": "BD",
    "PAKISTAN": "PK", "SRI LANKA": "LK", "EGYPT": "EG", "KENYA": "KE",
    "SOUTH AFRICA": "ZA", "BRAZIL": "BR", "MEXICO": "MX", "CANADA": "CA",
    "AUSTRALIA": "AU", "NEW ZEALAND": "NZ", "SAUDI ARABIA": "SA",
    "OMAN": "OM", "QATAR": "QA", "KUWAIT": "KW", "BAHRAIN": "BH",
    "GREECE": "GR", "PORTUGAL": "PT", "VENEZUELA": "VE", "UAE": "AE",
    "UNITED ARAB EMIRATES": "AE", "USA": "US", "US": "US",
    "UNITED STATES": "US", "UK": "GB", "UNITED KINGDOM": "GB",
}

# Kept for the degraded path: strip a trailing country token from a bare name so a
# name-only comparison still works when the table is absent.
COUNTRY_TOKENS = set(COUNTRY_WORDS)


def name_key(text: str) -> str:
    """The normalised lookup key. Must be applied identically to the table and to
    the document value, or nothing matches."""
    s = normalise_text(text)
    for prefix in _NAME_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return re.sub(r"\s+", " ", s).strip()


def _name_variants(name: str) -> set[str]:
    """The lookup forms a single table row offers.

    UN/LOCODE carries a location's alternative name in parentheses —
    `Nhava Sheva (Jawaharlal Nehru)` — and shipping documents use either half alone.
    Indexing both halves keeps lookup EXACT while covering the way the name is
    actually written; it is derived from the table's own data, not hand-written.
    Where splitting creates a collision, the ambiguity rule returns None, so this
    widens coverage without ever widening a guess.
    """
    if not name:
        return set()
    out = {name}
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", name)
    if m:
        head, inner = m.group(1).strip(), m.group(2).strip()
        if head:
            out.add(head)
        if inner:
            out.add(inner)
    return out


class PortResolver:
    """Loads once at construction, then pure: same input, same output, no I/O."""

    def __init__(self, unlocode_path: Path | str | None = None):
        self.by_code: dict[str, str] = {}          # LOCODE -> display name
        self.by_name: dict[str, set[str]] = {}     # normalised name -> {LOCODE, ...}
        self.loaded = False
        self.rows = 0
        if unlocode_path:
            self._load(Path(unlocode_path))

    def _load(self, path: Path) -> None:
        """A missing or corrupt table degrades to shape-recognition only. It never
        raises: the table is an enrichment, not a dependency."""
        try:
            raw = path.read_bytes()
        except OSError:
            return
        try:
            text = (gzip.decompress(raw) if path.suffix == ".gz" else raw).decode(
                "utf-8", errors="replace")
        except (OSError, EOFError, gzip.BadGzipFile):
            return

        try:
            for row in csv.DictReader(io.StringIO(text)):
                country = (row.get("Country") or "").strip().upper()
                loc = (row.get("Location") or "").strip().upper()
                if len(country) != 2 or len(loc) != 3:
                    continue
                code = country + loc
                name = (row.get("Name") or "").strip()
                plain = (row.get("NameWoDiacritics") or "").strip() or name
                if not name:
                    continue
                self.by_code.setdefault(code, plain)
                self.rows += 1
                for variant in _name_variants(name) | _name_variants(plain):
                    key = name_key(variant)
                    if key:
                        self.by_name.setdefault(key, set()).add(code)
        except (csv.Error, UnicodeDecodeError):
            return
        self.loaded = self.rows > 0

    # -- resolution ------------------------------------------------------

    def resolve(self, raw: str) -> tuple[str | None, str]:
        """Return (LOCODE, explanation). **None means unresolvable** — the caller
        must treat that as CANNOT_DETERMINE and never as a comparison result."""
        if not raw or not raw.strip():
            return None, "empty"
        if not self.loaded:
            return None, "no_reference_table"

        text = normalise_text(raw)

        # 1 — a code-shaped token, confirmed by table membership. The shape alone is
        #     not enough; five-letter words exist.
        for token in _TOKEN.findall(text):
            if LOCODE_SHAPE.match(token) and token in self.by_code:
                return token, f"code:{token}"

        # 2 — exact match on the normalised name.
        candidates = self.by_name.get(name_key(self._strip_countries(text)), set())
        if not candidates:
            candidates = self.by_name.get(name_key(text), set())

        if len(candidates) == 1:
            code = next(iter(candidates))
            return code, f"name:{code}"

        # 3 — ambiguous. Picking the first row invents a fact: Portland, Valencia and
        #     Victoria are real ports in several countries. A country signal in the
        #     same field may narrow it to exactly one, and only then.
        if len(candidates) > 1:
            country = self._country_signal(text)
            if country:
                narrowed = {c for c in candidates if c.startswith(country)}
                if len(narrowed) == 1:
                    code = next(iter(narrowed))
                    return code, f"name+country:{code}"
                if not narrowed:
                    return None, (f"ambiguous ({len(candidates)} codes) and the country "
                                  f"signal {country} matches none of them")
            return None, f"ambiguous: {len(candidates)} codes for this name"

        return None, "not_in_table"

    def identity(self, raw: str) -> tuple[str | None, str]:
        """A comparable identity for the port comparator.

        Prefers the LOCODE. With no table — or an unresolvable value — falls back to
        the normalised name, which is what this module did before UN/LOCODE shipped.
        The caller distinguishes the two via `resolve()`; this keeps the degraded
        path behaving exactly as it used to.
        """
        code, why = self.resolve(raw)
        if code is not None:
            return code, why
        bare = self._strip_countries(normalise_text(raw or ""))
        return (bare or None), (why if bare else "no_identity")

    # -- helpers ---------------------------------------------------------

    def _country_signal(self, text: str) -> str | None:
        """The ISO country a field's text names, if it names exactly one."""
        found = {COUNTRY_WORDS[w] for w in COUNTRY_WORDS
                 if re.search(rf"\b{re.escape(w)}\b", text)}
        return next(iter(found)) if len(found) == 1 else None

    @staticmethod
    def _strip_countries(text: str) -> str:
        """Remove known country tokens and parenthesised LOCODEs. Only KNOWN tokens —
        a blanket 'drop everything after the comma' destroys `Port Klang, Selangor`."""
        def drop_code(m: re.Match) -> str:
            inner = m.group(1).strip()
            return "" if LOCODE_SHAPE.match(inner) else m.group(0)

        s = re.sub(r"\(([^)]*)\)", drop_code, text).strip()
        parts = [p.strip() for p in re.split(r"[/,]| - ", s) if p.strip()]
        kept = [p for p in parts if p not in COUNTRY_TOKENS]

        # NEVER strip a country token that is the WHOLE field. Singapore, Hong Kong,
        # Macau, Malta, Djibouti, Gibraltar, Monaco, Bahrain, Qatar and Kuwait are all
        # both a country and a major port, and `Port of Loading: SINGAPORE` is a
        # complete, correct value. Stripping it emptied the identity on BOTH sides, so
        # the comparator saw two absent values and reported `unknown` — measured on 24
        # values in this corpus (23 × `SINGAPORE (SGSIN)`, 1 × `SINGAPORE`).
        #
        # The same guard covers `MALAYSIA / INDONESIA / CHINA` (2 occurrences): every
        # part is a country token, so stripping leaves nothing. Keeping the original is
        # strictly better than an empty identity — the comparator can still compare it
        # to the other side verbatim.
        if not kept:
            return re.sub(r"\s+", " ", s).strip()

        out = " ".join(kept)
        for token in sorted(COUNTRY_TOKENS, key=len, reverse=True):
            stripped = re.sub(rf"\b{re.escape(token)}\b\s*$", "", out).strip()
            if stripped:                    # same guard: never strip to nothing
                out = stripped
        return re.sub(r"\s+", " ", out).strip()
