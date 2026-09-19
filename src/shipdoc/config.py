"""M01 — load and validate fields.yaml / pipeline.yaml into frozen typed objects.

Validate at load, not at use: a typo in a field type must fail at startup, not at
record 380 of 520. Config is frozen and passed explicitly — `evaluate` needs it, and
a module-level singleton is how that dependency gets smuggled in.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml

from shipdoc.errors import ConfigError
from shipdoc.types import (
    Config,
    FeatureFlags,
    FieldSpec,
    FIELD_TYPES,
    LLMSettings,
    ThresholdPair,
    Thresholds,
)


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        raise ConfigError(f"missing config file: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(f"invalid YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _require(d: Mapping[str, Any], key: str, where: str) -> Any:
    """No silent defaults. A missing setting raises rather than falling back to a
    magic number buried in code."""
    if key not in d:
        raise ConfigError(f"missing required key '{key}' in {where}")
    return d[key]


def _decimal(value: Any, where: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ConfigError(f"{where}: {value!r} is not a number") from e


def _threshold_pair(d: Mapping[str, Any], name: str) -> ThresholdPair:
    block = _require(d, name, "pipeline.yaml:thresholds")
    if not isinstance(block, dict):
        raise ConfigError(f"pipeline.yaml:thresholds.{name} must be a mapping")
    pair = ThresholdPair(
        threshold=float(_require(block, "threshold", f"thresholds.{name}")),
        grey_low=float(_require(block, "grey_low", f"thresholds.{name}")),
    )
    if not 0.0 <= pair.grey_low <= pair.threshold <= 1.0:
        raise ConfigError(
            f"thresholds.{name}: require 0 <= grey_low <= threshold <= 1, got "
            f"grey_low={pair.grey_low}, threshold={pair.threshold}")
    return pair


def _field_spec(name: str, raw: Any) -> FieldSpec:
    if not isinstance(raw, dict):
        raise ConfigError(f"fields.{name} must be a mapping")

    ftype = _require(raw, "type", f"fields.{name}")
    if ftype not in FIELD_TYPES:
        raise ConfigError(
            f"fields.{name}.type = {ftype!r} is not a known comparator type; "
            f"expected one of {sorted(FIELD_TYPES)}")

    synonyms = _require(raw, "synonyms", f"fields.{name}")
    if not isinstance(synonyms, list) or not synonyms:
        raise ConfigError(f"fields.{name}.synonyms must be a non-empty list")

    conversions = {
        str(k): _decimal(v, f"fields.{name}.conversions.{k}")
        for k, v in (raw.get("conversions") or {}).items()
    }

    return FieldSpec(
        name=name,
        type=str(ftype),
        required=bool(_require(raw, "required", f"fields.{name}")),
        synonyms=tuple(str(s) for s in synonyms),
        anti_synonyms=tuple(str(s) for s in (raw.get("anti_synonyms") or ())),
        threshold=(None if raw.get("threshold") is None else float(raw["threshold"])),
        grey_low=(None if raw.get("grey_low") is None else float(raw["grey_low"])),
        unit=(None if raw.get("unit") is None else str(raw["unit"])),
        conversions=MappingProxyType(conversions),
        address_bearing=bool(raw.get("address_bearing", False)),
        extract_pattern=(None if raw.get("extract") is None else str(raw["extract"])),
    )


def load_config(path: Path) -> Config:
    """`path` is the config directory holding fields.yaml and pipeline.yaml."""
    path = Path(path)
    fields_raw = _read_yaml(path / "fields.yaml")
    pipe_raw = _read_yaml(path / "pipeline.yaml")

    raw_fields = _require(fields_raw, "fields", "fields.yaml")
    if not isinstance(raw_fields, dict) or not raw_fields:
        raise ConfigError("fields.yaml:fields must be a non-empty mapping")
    fields = {name: _field_spec(name, spec) for name, spec in raw_fields.items()}

    sentinels = _require(fields_raw, "sentinels", "fields.yaml")
    if not isinstance(sentinels, list):
        raise ConfigError("fields.yaml:sentinels must be a list of regexes")

    th = _require(pipe_raw, "thresholds", "pipeline.yaml")
    thresholds = Thresholds(
        min_extract_chars=int(_require(th, "min_extract_chars", "thresholds")),
        min_labels_present=int(_require(th, "min_labels_present", "thresholds")),
        pdf_space_ratio_min=float(_require(th, "pdf_space_ratio_min", "thresholds")),
        quantity_epsilon=_decimal(
            _require(th, "quantity_epsilon", "thresholds"), "thresholds.quantity_epsilon"),
        name_strict=_threshold_pair(th, "name_strict"),
        name_address=_threshold_pair(th, "name_address"),
    )

    lm = _require(pipe_raw, "llm", "pipeline.yaml")
    llm = LLMSettings(
        model=str(_require(lm, "model", "llm")),
        prompt_version=str(_require(lm, "prompt_version", "llm")),
        timeout_s=float(_require(lm, "timeout_s", "llm")),
        temperature=float(_require(lm, "temperature", "llm")),
        seed=(None if lm.get("seed") is None else int(lm["seed"])),
    )

    fl = _require(pipe_raw, "flags", "pipeline.yaml")
    flags = FeatureFlags(
        ocr_enabled=bool(_require(fl, "ocr_enabled", "flags")),
        parallel_workers=int(_require(fl, "parallel_workers", "flags")),
        structural_decisive=bool(_require(fl, "structural_decisive", "flags")),
        port_resolution_enabled=bool(fl.get("port_resolution_enabled", False)),
    )

    # Reference data path, relative to the config directory. Optional: absent file
    # means the port resolver degrades to shape-recognition, which is the behaviour
    # that existed before UN/LOCODE shipped.
    ref = pipe_raw.get("reference") or {}
    unlocode_name = ref.get("unlocode")
    unlocode_path = (path / str(unlocode_name)) if unlocode_name else None
    if unlocode_path is not None and not unlocode_path.is_file():
        unlocode_path = None

    return Config(
        fields=MappingProxyType(fields),
        comparison_category=str(_require(fields_raw, "comparison_category", "fields.yaml")),
        sentinels=tuple(str(s) for s in sentinels),
        thresholds=thresholds,
        llm=llm,
        flags=flags,
        unlocode_path=unlocode_path,
    )
