"""M09 `normalise/ports.py` — UN/LOCODE resolution.

Written BEFORE the implementation. The first test is the one that matters: an
earlier draft of this idea had

    code = TABLE.get(cleaned, cleaned)      # WRONG

which silently falls back to the raw string, so two unresolvable values get
string-compared and can produce a confident MATCH or MISMATCH out of nothing.
`resolve()` must return None when it cannot resolve, and None must propagate as
CANNOT_DETERMINE.
"""
import gzip
import io

import pytest

from conftest import CONFIG_DIR
from shipdoc.config import load_config
from shipdoc.normalise.ports import PortResolver

# A tiny fixture table. Real columns, four locations, one deliberate name collision
# (Valencia exists in both ES and VE) and one five-letter word that is NOT a code.
FIXTURE_ROWS = [
    ("MY", "PKG", "Port Klang", "Port Klang"),
    ("PE", "CLL", "Callao", "Callao"),
    ("ES", "VLC", "Valencia", "Valencia"),
    ("VE", "VLN", "Valencia", "Valencia"),
    ("SG", "SIN", "Singapore", "Singapore"),
]

HEADER = ("Change,Country,Location,Name,NameWoDiacritics,Subdivision,Status,"
          "Function,Date,IATA,Coordinates,Remarks")


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    p = tmp_path_factory.mktemp("unlocode") / "unlocode.csv.gz"
    lines = [HEADER] + [
        f",{c},{l},{n},{nw},,AI,1-------,0601,,," for c, l, n, nw in FIXTURE_ROWS
    ]
    with gzip.open(p, "wt", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


@pytest.fixture(scope="module")
def resolver(table):
    return PortResolver(table)


@pytest.fixture(scope="module")
def empty_resolver():
    """No table at all — the degraded path that must behave like it always did."""
    return PortResolver(None)


# --------------------------------------------------------------------------
# THE bug: unresolvable MUST be None, never a fallback to the raw string
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "ZZZZZ",                      # code-shaped, not in the table
    "NOWHERESVILLE",              # name, not in the table
    "QQQQQ, ATLANTIS",            # neither
    "",                           # empty
    "   ",                        # whitespace
])
def test_unresolvable_returns_none_never_the_raw_string(resolver, raw):
    code, _why = resolver.resolve(raw)
    assert code is None, f"resolver invented {code!r} from {raw!r}"


def test_no_silent_fallback_to_input(resolver):
    """Explicitly: the return value is never the cleaned input echoed back."""
    for raw in ("ZZZZZ", "NOWHERESVILLE", "PORT OF ATLANTIS"):
        code, _ = resolver.resolve(raw)
        assert code != raw and code != raw.upper().replace(" ", "")


# --------------------------------------------------------------------------
# Resolution order 1 — a code token, but only if the table confirms it
# --------------------------------------------------------------------------

def test_resolves_an_exact_code(resolver):
    assert resolver.resolve("MYPKG")[0] == "MYPKG"


def test_resolves_a_code_embedded_in_text(resolver):
    assert resolver.resolve("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")[0] == "MYPKG"


def test_code_shape_alone_is_not_enough(resolver):
    """Five-letter words exist. Table membership is what makes it a code."""
    assert resolver.resolve("ZZZZZ")[0] is None


@pytest.mark.parametrize("word", ["HOUSE", "TRAIN", "CRANE", "WATER"])
def test_ordinary_five_letter_words_do_not_resolve(resolver, word):
    assert resolver.resolve(word)[0] is None


# --------------------------------------------------------------------------
# Resolution order 2 — exact match on a normalised name
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Port Klang", "MYPKG"),
    ("PORT KLANG", "MYPKG"),
    ("port  klang", "MYPKG"),
    ("Port of Klang", "MYPKG"),
    ("CALLAO", "PECLL"),
    ("Callao, Peru", "PECLL"),
    ("SINGAPORE", "SGSIN"),
])
def test_resolves_names_after_normalisation(resolver, raw, expected):
    assert resolver.resolve(raw)[0] == expected


def test_name_lookup_is_exact_not_fuzzy(resolver):
    """No fuzzy matching into the table. A 110k-row table plus fuzzy matching
    produces confident garbage."""
    for near_miss in ("Port Klangg", "Kallao", "Singapor", "Prt Klang"):
        assert resolver.resolve(near_miss)[0] is None, near_miss


# --------------------------------------------------------------------------
# Resolution order 3 — ambiguity is NOT resolved by picking the first row
# --------------------------------------------------------------------------

def test_ambiguous_name_returns_none(resolver):
    """Valencia is a real port in both ES and VE. Picking one invents a fact."""
    code, why = resolver.resolve("Valencia")
    assert code is None
    assert "ambiguous" in why.lower()


def test_country_signal_disambiguates_when_it_names_exactly_one(resolver):
    assert resolver.resolve("Valencia, Spain")[0] == "ESVLC"
    assert resolver.resolve("VALENCIA, VENEZUELA")[0] == "VEVLN"


def test_country_signal_that_matches_nothing_stays_none(resolver):
    assert resolver.resolve("Valencia, Malaysia")[0] is None


# --------------------------------------------------------------------------
# Purity and determinism
# --------------------------------------------------------------------------

def test_resolver_is_pure(resolver):
    a = [resolver.resolve("Port Klang") for _ in range(5)]
    assert len(set(a)) == 1


def test_two_resolvers_on_one_table_agree(table):
    assert PortResolver(table).resolve("CALLAO") == PortResolver(table).resolve("CALLAO")


# --------------------------------------------------------------------------
# Degraded mode — the table is an ENRICHMENT, not a requirement
# --------------------------------------------------------------------------

def test_missing_table_does_not_crash(empty_resolver):
    code, why = empty_resolver.resolve("MYPKG")
    assert code is None
    assert why


def test_missing_table_still_gives_a_comparable_identity(empty_resolver):
    """Pre-LOCODE behaviour: no code, but a normalised name to fall back on."""
    assert empty_resolver.identity("PORT KLANG, MALAYSIA")[0] == "PORT KLANG"


def test_nonexistent_path_is_not_an_error(tmp_path):
    r = PortResolver(tmp_path / "does-not-exist.csv.gz")
    assert r.resolve("MYPKG")[0] is None
    assert r.loaded is False


def test_corrupt_table_is_not_an_error(tmp_path):
    p = tmp_path / "bad.csv.gz"
    p.write_bytes(b"this is not gzip")
    r = PortResolver(p)
    assert r.resolve("MYPKG")[0] is None
    assert r.loaded is False


# --------------------------------------------------------------------------
# The real shipped table
# --------------------------------------------------------------------------

def test_shipped_table_loads_and_resolves_known_corpus_ports():
    cfg = load_config(CONFIG_DIR)
    r = PortResolver(cfg.unlocode_path)
    assert r.loaded, "config/unlocode.csv.gz should be present and readable"
    assert r.rows > 100_000
    # Ports that actually appear in this corpus.
    assert r.resolve("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)")[0] == "MYPKG"
    assert r.resolve("CALLAO, PERU (PECLL)")[0] == "PECLL"
    assert r.resolve("NHAVA SHEVA, INDIA")[0] is not None
