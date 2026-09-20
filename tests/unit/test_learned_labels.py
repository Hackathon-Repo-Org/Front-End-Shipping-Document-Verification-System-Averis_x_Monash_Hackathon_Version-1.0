"""Phase 11 — the learned label vocabulary.

    AI PROPOSES  ·  A HUMAN APPROVES  ·  RULES EXECUTE

The tests here are ordered by how much damage the thing they protect would do:
first the hard line on what may be learned, then load-time conflicts, then the
proposal path, then detection, then inertness.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shipdoc.errors import ConfigError
from shipdoc.learned import (
    FILENAME,
    apply_to_fields,
    load_learned,
    normalise_label,
)
from shipdoc.types import FieldSpec

GOOD = {
    "label": "Containers:",
    "field": "container_count",
    "decision": "approve",
    "approved_by": "a.reviewer",
    "approved_at": "2026-09-20T00:00:00+00:00",
    "model": "qwen2.5:7b-instruct",
    "prompt_version": "labels-v1",
}


def _fields():
    return {
        "container_count": FieldSpec(name="container_count", type="integer",
                                     required=True, synonyms=("Container Count:",)),
        "gross_weight_kg": FieldSpec(name="gross_weight_kg", type="quantity",
                                     required=True, synonyms=("Gross Weight:",),
                                     anti_synonyms=("NET WEIGHT:",)),
    }


def _write(tmp_path: Path, entries: list[dict]) -> Path:
    import yaml
    (tmp_path / FILENAME).write_text(yaml.safe_dump({"labels": entries}),
                                     encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------- THE HARD LINE

@pytest.mark.parametrize("bad_key", ["value", "alias", "equals", "same_as",
                                     "si_value", "bl_value"])
def test_value_alias_entry_is_rejected(tmp_path, bad_key):
    """THE test this phase turns on.

    A rule saying two VALUES mean the same thing must never be learnable. It is a
    judgement about whether two documents AGREE — the one thing this system never
    delegates to a model — and as a permanent global rule it would make the system
    blind to a genuine change of that party on every future shipment.

    Parametrised over every shape the attempt could take, because rejecting only the
    spelling someone happened to try first is not enforcement.
    """
    entry = dict(GOOD, **{bad_key: "ABC Trading Sdn Bhd"})
    _write(tmp_path, [entry])
    with pytest.raises(ConfigError) as e:
        load_learned(tmp_path, _fields())
    msg = str(e.value)
    assert "VALUE equivalence" in msg
    assert bad_key in msg
    # The error must explain WHY, not just refuse — someone will meet it at 2am.
    assert "blind" in msg


def test_a_plain_label_mapping_is_accepted(tmp_path):
    """The other half: the permitted case must actually work."""
    _write(tmp_path, [GOOD])
    vocab = load_learned(tmp_path, _fields())
    assert len(vocab.approved) == 1
    assert vocab.approved[0].field == "container_count"
    assert vocab.sha256 and vocab.present


def test_unknown_keys_are_rejected(tmp_path):
    _write(tmp_path, [dict(GOOD, confidence=0.91)])
    with pytest.raises(ConfigError, match="unknown key"):
        load_learned(tmp_path, _fields())


# --------------------------------------------------------------- PROVENANCE

@pytest.mark.parametrize("missing", ["approved_by", "approved_at", "model",
                                     "prompt_version"])
def test_an_entry_without_provenance_is_rejected(tmp_path, missing):
    """A learned rule with no provenance cannot be audited and should not exist."""
    entry = {k: v for k, v in GOOD.items() if k != missing}
    _write(tmp_path, [entry])
    with pytest.raises(ConfigError, match="required"):
        load_learned(tmp_path, _fields())


def test_unknown_field_is_rejected(tmp_path):
    _write(tmp_path, [dict(GOOD, field="vessel_name")])
    with pytest.raises(ConfigError, match="not a compared field"):
        load_learned(tmp_path, _fields())


def test_bad_decision_is_rejected(tmp_path):
    _write(tmp_path, [dict(GOOD, decision="maybe")])
    with pytest.raises(ConfigError, match="decision must be"):
        load_learned(tmp_path, _fields())


# ---------------------------------------------------------------- CONFLICTS

def test_learned_label_may_not_contradict_an_anti_synonym(tmp_path):
    """ERROR at load time, not a warning.

    A warning here is a run that mis-extracts every gross weight in the corpus and
    mentions it in a line you scrolled past.
    """
    _write(tmp_path, [dict(GOOD, label="NET WEIGHT:", field="gross_weight_kg")])
    with pytest.raises(ConfigError, match="contradicts the hand-written anti_synonym"):
        load_learned(tmp_path, _fields())


def test_one_label_may_not_name_two_fields(tmp_path):
    _write(tmp_path, [
        dict(GOOD, label="Total:", field="container_count"),
        dict(GOOD, label="Total:", field="gross_weight_kg"),
    ])
    with pytest.raises(ConfigError, match="cannot name two fields"):
        load_learned(tmp_path, _fields())


def test_the_same_label_approved_twice_for_one_field_is_fine(tmp_path):
    """Duplicate approvals are redundant, not contradictory. Do not error."""
    _write(tmp_path, [GOOD, dict(GOOD, approved_by="someone.else")])
    assert len(load_learned(tmp_path, _fields()).approved) == 2


# ------------------------------------------------------------------ EFFECT

def test_approval_becomes_a_synonym_and_rejection_an_anti_synonym(tmp_path):
    _write(tmp_path, [
        GOOD,
        dict(GOOD, label="Vessel:", field="container_count", decision="reject"),
    ])
    vocab = load_learned(tmp_path, _fields())
    out = apply_to_fields(_fields(), vocab)
    assert "Containers:" in out["container_count"].synonyms
    assert "Vessel:" in out["container_count"].anti_synonyms


def test_rejections_are_recorded_so_the_question_does_not_return(tmp_path):
    """Without this a reviewer is asked the same thing every week and stops reading."""
    _write(tmp_path, [dict(GOOD, decision="reject")])
    vocab = load_learned(tmp_path, _fields())
    assert len(vocab.rejected) == 1
    from shipdoc.review.proposals import already_known
    assert already_known(normalise_label("Containers:"), vocab, []) is True


# ------------------------------------------------------------------- INERT

def test_absent_file_is_inert(tmp_path):
    vocab = load_learned(tmp_path, _fields())
    assert vocab.entries == () and vocab.sha256 == "" and vocab.present is False
    assert apply_to_fields(_fields(), vocab) == _fields()


def test_the_key_agrees_with_the_extractor(tmp_path):
    """`learned.normalise_label` duplicates `normalise.labels.label_key` because a
    foundation module may not import `normalise`. This is what keeps them honest."""
    from shipdoc.normalise.labels import label_key
    for s in ["Containers:", "  TOTAL  Gross Weight (KG): ", "Gross Weight毛重(KGS):",
              "No. of Containers or Packages:"]:
        assert normalise_label(s) == label_key(s), s
