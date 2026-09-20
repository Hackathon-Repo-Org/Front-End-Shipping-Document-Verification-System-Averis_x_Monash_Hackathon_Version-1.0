"""M01b — load `config/learned_labels.yaml`: the approved label vocabulary.

    AI PROPOSES  ·  A HUMAN APPROVES  ·  RULES EXECUTE

Nothing a model suggests takes effect here. This module reads only what a person has
already approved, and once approved it is an ordinary deterministic rule — free,
auditable, and applied identically forever.

WHAT MAY AND MAY NOT BE LEARNED
-------------------------------
Learnable, globally and permanently:
  * label -> field mappings      `Containers:` names container_count
  * anti-mappings                a reviewer rejected one, so never ask again
  * formatting normalisation     `SDN. BHD.` and `SDN BHD` are one spelling

NEVER learnable as a global rule:
  * that two VALUES are equivalent — `ABC Trdg Co` = `ABC Trading Sdn Bhd`

That last one is the whole reason this file validates rather than trusts. A value
equivalence is a judgement about whether two documents AGREE, which is the one thing
this system never delegates to a model. Worse, writing it as a global rule would make
the system permanently blind to a genuine party change on every future shipment: the
day `ABC Trading Sdn Bhd` really is replaced by `ABC Trdg Co` on a bill of lading, the
rule says "fine" forever. A reviewer may still decide that for ONE record through the
existing Decision mechanism, where it stays attached to the record it was judged on.

`_validate_shape` rejects any entry that is not a label->field mapping, and
`tests/unit/test_learned_labels.py::test_value_alias_entry_is_rejected` proves it.

SEPARATE FILE, ON PURPOSE
-------------------------
This is not merged into fields.yaml. Keeping it apart means the learned set can be
diffed on its own, disabled wholesale by renaming one file, and rolled back without
touching anything a human wrote by hand.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from shipdoc.errors import ConfigError
from shipdoc.types import FieldSpec, LearnedLabel, LearnedVocabulary

FILENAME = "learned_labels.yaml"

DECISIONS = ("approve", "reject")

# Exactly the keys an entry may carry. Anything else is a different KIND of rule
# wearing this file's clothes, and it is refused rather than ignored.
_REQUIRED = ("label", "field", "decision", "approved_by", "approved_at",
             "model", "prompt_version")
_OPTIONAL = ("note", "normalised")

# Keys that betray an attempt to learn a VALUE equivalence rather than a label
# mapping. Named explicitly so the error message can say what is wrong and why,
# instead of "unknown key".
_VALUE_ALIAS_KEYS = ("value", "values", "alias", "aliases", "equals", "equivalent",
                     "same_as", "si_value", "bl_value", "left", "right", "maps_to")


def normalise_label(text: str) -> str:
    """The key. Must agree with normalise.labels.label_key — asserted by a test.

    Duplicated rather than imported: `config` is a foundation layer and may not
    import `normalise`, which sits far above it. The test is what keeps the two
    honest; a comment would not.
    """
    import unicodedata
    norm = unicodedata.normalize("NFKC", text)
    ascii_only = "".join(ch for ch in norm if ord(ch) < 128)
    return re.sub(r"\s+", " ", ascii_only).strip().rstrip(":").strip().lower()


def _validate_shape(raw: Any, where: str) -> None:
    """THE HARD LINE. Refuse anything that is not a label->field mapping."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{where}: each entry must be a mapping, got {type(raw).__name__}")

    offending = [k for k in _VALUE_ALIAS_KEYS if k in raw]
    if offending:
        raise ConfigError(
            f"{where}: refused — key(s) {offending} look like a VALUE equivalence.\n"
            f"  This file learns label->field mappings only. A rule saying two VALUES\n"
            f"  mean the same thing is never learned globally: it is a judgement about\n"
            f"  whether two documents agree, and as a permanent rule it would make the\n"
            f"  system blind to a genuine change of that party on every future shipment.\n"
            f"  Decide it for ONE record with the review-queue `decision` field instead.")

    unknown = set(raw) - set(_REQUIRED) - set(_OPTIONAL)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}; "
                          f"allowed: {sorted(_REQUIRED + _OPTIONAL)}")
    for key in _REQUIRED:
        if not str(raw.get(key) or "").strip():
            raise ConfigError(f"{where}: '{key}' is required and must be non-empty "
                              f"(a learned rule with no provenance cannot be audited)")
    if raw["decision"] not in DECISIONS:
        raise ConfigError(f"{where}: decision must be one of {DECISIONS}, "
                          f"got {raw['decision']!r}")


def load_learned(config_dir: Path, fields: Mapping[str, FieldSpec]) -> LearnedVocabulary:
    """Read, validate and hash the learned file. Absent file => inert empty set."""
    path = Path(config_dir) / FILENAME
    if not path.is_file():
        return LearnedVocabulary(entries=(), sha256="", path=str(path), present=False)

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()

    import yaml
    try:
        doc = yaml.safe_load(data.decode("utf-8")) or {}
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML: {e}") from e
    if not isinstance(doc, dict):
        raise ConfigError(f"{path}: top level must be a mapping with a 'labels' key")

    raw_entries = doc.get("labels") or []
    if not isinstance(raw_entries, list):
        raise ConfigError(f"{path}: 'labels' must be a list")

    entries: list[LearnedLabel] = []
    for i, raw in enumerate(raw_entries):
        where = f"{path}:labels[{i}]"
        _validate_shape(raw, where)
        field_name = str(raw["field"])
        if field_name not in fields:
            raise ConfigError(
                f"{where}: field {field_name!r} is not a compared field; "
                f"known fields are {sorted(fields)}")
        entries.append(LearnedLabel(
            label=str(raw["label"]),
            normalised=normalise_label(str(raw.get("normalised") or raw["label"])),
            field=field_name,
            decision=str(raw["decision"]),
            approved_by=str(raw["approved_by"]),
            approved_at=str(raw["approved_at"]),
            model=str(raw["model"]),
            prompt_version=str(raw["prompt_version"]),
            note=str(raw.get("note") or ""),
        ))

    _check_conflicts(entries, fields, path)
    return LearnedVocabulary(entries=tuple(entries), sha256=digest,
                             path=str(path), present=True)


def _check_conflicts(entries: list[LearnedLabel], fields: Mapping[str, FieldSpec],
                     path: Path) -> None:
    """Both of these are ERRORS at load time, not warnings.

    A warning on a vocabulary conflict is a run that produces wrong extractions and
    tells you about it in a line you scrolled past.
    """
    # 1. A learned label may not contradict a hand-written anti_synonym.
    forbidden: dict[str, str] = {}
    for fname, spec in fields.items():
        for anti in spec.anti_synonyms:
            forbidden[normalise_label(anti)] = fname
    for e in entries:
        if e.decision != "approve":
            continue
        owner = forbidden.get(e.normalised)
        if owner is not None:
            raise ConfigError(
                f"{path}: learned label {e.label!r} -> {e.field} contradicts the "
                f"hand-written anti_synonym on field {owner!r} in fields.yaml.\n"
                f"  fields.yaml is authoritative. Remove the learned entry, or remove\n"
                f"  the anti_synonym — deliberately, and not both at once.")

    # 2. The same normalised label may not mean two different things.
    owner_of: dict[str, LearnedLabel] = {}
    for e in entries:
        if e.decision != "approve":
            continue
        prior = owner_of.get(e.normalised)
        if prior is not None and prior.field != e.field:
            raise ConfigError(
                f"{path}: label {e.normalised!r} is approved for BOTH "
                f"{prior.field!r} (by {prior.approved_by} on {prior.approved_at}) and "
                f"{e.field!r} (by {e.approved_by} on {e.approved_at}).\n"
                f"  One label cannot name two fields. Reject one of them.")
        owner_of.setdefault(e.normalised, e)


def apply_to_fields(fields: dict[str, FieldSpec],
                    vocab: LearnedVocabulary) -> dict[str, FieldSpec]:
    """Fold approvals into synonyms and rejections into anti_synonyms.

    Rejections matter as much as approvals. Without them the same question returns
    every week, the queue fills with things a person has already said no to, and the
    reviewer stops reading it — at which point the approval step is theatre.
    """
    if not vocab.entries:
        return fields
    from dataclasses import replace

    add_syn: dict[str, list[str]] = {}
    add_anti: dict[str, list[str]] = {}
    for e in vocab.entries:
        (add_syn if e.decision == "approve" else add_anti).setdefault(
            e.field, []).append(e.label)

    out = dict(fields)
    for fname, spec in out.items():
        syn, anti = add_syn.get(fname), add_anti.get(fname)
        if not syn and not anti:
            continue
        # Longest-first, across the hand-written and learned sets together.
        #
        # This is not cosmetic. M09's P-LONGEST says declaration order IS matching
        # order: match `Port of Loading:` before `Port of Loading (POL):` and `(POL):`
        # is stranded in the value. `LabelIndex` re-sorts by length and is the real
        # authority, but leaving this list out of order makes the config lie about
        # what happens, and `test_synonyms_are_declared_longest_first` is what caught
        # it — appending learned entries at the end broke the invariant on the first
        # approval.
        out[fname] = replace(
            spec,
            synonyms=tuple(sorted(set(tuple(spec.synonyms) + tuple(syn or ())),
                                  key=lambda s: (-len(s), s))),
            anti_synonyms=tuple(sorted(set(tuple(spec.anti_synonyms) + tuple(anti or ())),
                                       key=lambda s: (-len(s), s))),
        )
    return out
