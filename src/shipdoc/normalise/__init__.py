"""M09 — ExtractedDoc to a canonical {field: FieldValue} map.

Both documents are normalised with THE SAME function object. The classic bug is
normalising in the extractor on one path and in the comparator on the other, which
produces guaranteed false alarms.
"""
from __future__ import annotations

from shipdoc.normalise.labels import LabelIndex, harvest
from shipdoc.normalise.ports import PortResolver
from shipdoc.normalise.sentinels import compile_sentinels, is_sentinel
from shipdoc.normalise.values import (
    normalise_text,
    parse_container_count,
    parse_quantity,
)
from shipdoc.normalise.verify import appears_in
from shipdoc.types import Config, ExtractedDoc, FieldValue, Method, SourceRef

AMBIGUOUS = "ambiguous_multiple_values"


class Normaliser:
    """Built once per run and shared by both documents (M09's same-function rule)."""

    def __init__(self, cfg: Config, ports: PortResolver | None = None):
        self.cfg = cfg
        self.index = LabelIndex(cfg)
        self.sentinels = compile_sentinels(cfg.sentinels)
        # The UN/LOCODE table is gated by the SAME flag that gates the comparator.
        # PortResolver.identity() returns a LOCODE when the table is loaded, which
        # changes FieldValue.normalised for every resolvable port — so loading the
        # table while the flag is off would leak Phase 5 behaviour into the values
        # even though the resolver never reaches cmp_port. Flag off => no table.
        table = (getattr(cfg, "unlocode_path", None)
                 if cfg.flags.port_resolution_enabled else None)
        self.ports = ports or PortResolver(table)

    def normalise(self, doc: ExtractedDoc, ref: str) -> dict[str, FieldValue]:
        if not doc.ok:
            return {}
        found = harvest(doc.text, self.index)
        out: dict[str, FieldValue] = {}

        for field, (label_seen, raw_value, line_no) in found.items():
            spec = self.cfg.fields[field]
            ambiguous = line_no < 0
            locator = f"line {abs(line_no)}"

            # T3 first: a value that is not in the extracted text was invented.
            if not appears_in(raw_value, doc.text):
                continue

            normalised = self._normalise_one(field, raw_value, spec)
            out[field] = FieldValue(
                field=field,
                raw_text=raw_value,
                normalised=normalised,
                source=SourceRef(file=ref, locator=locator),
                method=doc.method,
                label_seen=(AMBIGUOUS if ambiguous else label_seen),
            )
        return out

    def _normalise_one(self, field: str, raw: str, spec):
        # Sentinels map to None BEFORE a comparator ever sees the value (T5). In this
        # corpus a missing value is a non-empty string: `N/A`, `TBA`, `_______ MTS`.
        if is_sentinel(raw, self.sentinels):
            return None
        if spec.type == "quantity":
            return parse_quantity(raw, spec)[0]
        if spec.type == "integer":
            return parse_container_count(raw, spec)[0]
        if spec.type == "port":
            return self.ports.identity(raw)[0]
        return normalise_text(raw) or None

    def detail_for(self, field: str, raw: str) -> str:
        """The interpretation, recorded so a reviewer can see what was assumed."""
        spec = self.cfg.fields[field]
        if raw is None:
            return "absent"
        if is_sentinel(raw, self.sentinels):
            return "sentinel"
        if spec.type == "quantity":
            return parse_quantity(raw, spec)[1]
        if spec.type == "integer":
            return parse_container_count(raw, spec)[1]
        if spec.type == "port":
            return self.ports.identity(raw)[1]
        return "text"
