"""The field registry is now the single authority on cardinality (the C1 fix), so it
needs its own guard.

With Appendix A's five-field registry the cardinality assertion would have compared
5 == 5 and passed, `notify_party` and `port_of_discharge` would never have been
compared, and nothing anywhere would have complained.
"""
import re
from pathlib import Path

from conftest import CONFIG_DIR, DATASET_DIR, ROOT
from shipdoc.config import load_config
from shipdoc.types import FIELD_TYPES

SEVEN = {
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
    "container_count", "gross_weight_kg",
}


def test_field_registry_is_exactly_the_seven():
    assert set(load_config(CONFIG_DIR).fields) == SEVEN


def test_registry_field_names_match_the_readme():
    """The seven names are attested verbatim in README.md (Open Item 1, CLOSED).
    If the README ever disagrees with fields.yaml, the submission silently scores
    zero on every correctly-detected mismatch."""
    readme = (DATASET_DIR / "README.md").read_text(encoding="utf-8")
    for name in SEVEN:
        assert re.search(rf"\b{re.escape(name)}\b", readme), \
            f"{name} is not attested in README.md"


def test_every_field_type_is_a_known_comparator_type():
    cfg = load_config(CONFIG_DIR)
    assert {f.type for f in cfg.fields.values()} <= FIELD_TYPES


def test_every_field_has_at_least_one_synonym():
    cfg = load_config(CONFIG_DIR)
    for name, spec in cfg.fields.items():
        assert spec.synonyms, f"{name} has no label synonyms — it can never be extracted"


def test_gross_weight_has_anti_synonyms():
    """M09 P-NET. Without a negative list, any substring match on 'weight' captures
    NET WEIGHT, and email_516_SI.txt carries both."""
    spec = load_config(CONFIG_DIR).fields["gross_weight_kg"]
    assert spec.anti_synonyms
    assert any("NET" in a.upper() for a in spec.anti_synonyms)


def test_synonyms_are_declared_longest_first():
    """M09: matching `Port of Loading:` before `Port of Loading (POL):` strands
    `(POL):` in the value. Declaration order is the matching order."""
    for name, spec in load_config(CONFIG_DIR).fields.items():
        lengths = [len(s) for s in spec.synonyms]
        assert lengths == sorted(lengths, reverse=True), \
            f"{name}: synonyms must be declared longest-first, got {spec.synonyms}"


# --------------------------------------------------------------------------
# HARD RULE 4 — exactly two sites assign Record.state (patch §4)
# --------------------------------------------------------------------------

def test_exactly_two_state_assignment_sites():
    """`_halted()` is exact only while this holds. Assert the rule, do not trust it."""
    src = ROOT / "src" / "shipdoc"
    pattern = re.compile(r"^\s*(?!#)\S*\brec(?:ord)?\.state\s*(?:,[^=]*)?=(?!=)", re.M)
    sites = []
    for py in src.rglob("*.py"):
        for m in pattern.finditer(py.read_text(encoding="utf-8")):
            line = m.group(0).strip()
            sites.append(f"{py.relative_to(src).as_posix()}: {line}")

    expected_files = {"state/machine.py", "pipeline.py"}
    found_files = {s.split(":")[0] for s in sites}
    assert found_files == expected_files, (
        f"Record.state must be assigned in exactly {sorted(expected_files)}; "
        f"found {sorted(found_files)} -> {sites}")
    assert len(sites) == 2, f"expected exactly 2 assignment sites, found {sites}"
