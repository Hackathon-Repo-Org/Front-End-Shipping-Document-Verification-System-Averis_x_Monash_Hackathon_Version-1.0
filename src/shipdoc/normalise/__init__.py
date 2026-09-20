"""M09 — ExtractedDoc to a canonical {field: FieldValue} map.

Both documents are normalised with THE SAME function object. The classic bug is
normalising in the extractor on one path and in the comparator on the other, which
produces guaranteed false alarms.
"""
from __future__ import annotations

from dataclasses import replace

from shipdoc.normalise.labels import LabelIndex, harvest
from shipdoc.normalise.ports import PortResolver
from shipdoc.normalise.referential import (
    MAX_HOPS,
    classify_reference,
    target_field,
)
from shipdoc.normalise.sentinels import compile_sentinels, is_sentinel
from shipdoc.normalise.values import (
    normalise_text,
    parse_container_count,
    parse_quantity,
)
from shipdoc.normalise.verify import appears_in
from shipdoc.types import Config, ExtractedDoc, FieldValue, Method, SourceRef

AMBIGUOUS = "ambiguous_multiple_values"
# Phase 10. The document pointed at another field and we could not follow the
# pointer — the target is absent, the chain dead-ends, or it cycles. This is an
# uncertainty, never a defect, so comparators must read it before the
# asymmetric-presence rules.
UNRESOLVED_REFERENCE = "unresolved_reference"


class Normaliser:
    """Built once per run and shared by both documents (M09's same-function rule)."""

    def __init__(self, cfg: Config, ports: PortResolver | None = None):
        self.cfg = cfg
        self.index = LabelIndex(cfg)
        # Reference targets are matched against the SAME label vocabulary the
        # extractor uses, so `SAME AS CONSIGNEE` and a `Consignee:` label agree by
        # construction and a new synonym improves both at once.
        self._label_to_field = {key: field for key, field, _pat in self.index.entries}
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
        return self.normalise_with_labels(doc, ref)[0]

    def normalise_with_labels(
        self, doc: ExtractedDoc, ref: str,
    ) -> tuple[dict[str, FieldValue], frozenset[str]]:
        """Values, plus the set of fields whose LABEL was matched in this document.

        Phase 10. The second element is NOT `set(out)`: a label can be found and
        still yield no entry, because T3 rejected the value as unverifiable. A
        reviewer told "no gross-weight label in this BL" when in fact we found the
        label and distrusted the value has been told the wrong thing.
        """
        if not doc.ok:
            return {}, frozenset()
        found = harvest(doc.text, self.index)
        seen = frozenset(found)
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
        self._resolve_references(out, found)
        return out, seen

    # ------------------------------------------------------------ references
    def _resolve_references(self, out: dict[str, FieldValue],
                            found: dict[str, tuple[str, str, int]]) -> None:
        """Phase 10 Fix 2. Substitute `SAME AS CONSIGNEE` and friends IN PLACE.

        Resolution is within ONE document — see referential.py for why crossing to
        the other document would make the comparison incapable of failing.
        """
        refs: dict[str, tuple[str, str | None]] = {}
        for field, fv in out.items():
            kind = classify_reference(fv.raw_text)
            if kind is not None:
                refs[field] = kind
        if not refs:
            return

        # Positional order, for `SAME AS ABOVE` and ditto marks.
        order = sorted((abs(found[f][2]), f) for f in found if f in out)
        prev_of = {f: order[i - 1][1] if i else None
                   for i, (_ln, f) in enumerate(order)}

        # Which field does each reference point AT?
        points_to: dict[str, str | None] = {}
        for field, (kind, target) in refs.items():
            if kind == "named":
                points_to[field] = target_field(target or "", self._label_to_field)
            else:
                points_to[field] = prev_of.get(field)

        for field in refs:
            resolved = self._follow(field, points_to, out)
            fv = out[field]
            if resolved is None:
                # Unresolvable, dead-ended or circular. NOT a defect and NOT a guess.
                out[field] = replace(fv, normalised=None,
                                     label_seen=UNRESOLVED_REFERENCE,
                                     reference_text=fv.raw_text)
            else:
                src = out[resolved]
                # Substitute BOTH forms. `normalised` alone is not enough: the party
                # comparator splits company name from address out of `raw_text`, so a
                # half-substituted value compares the pointer string against a real
                # company name and reports the defect this fix exists to remove.
                out[field] = replace(fv, raw_text=src.raw_text,
                                     normalised=src.normalised,
                                     resolved_from=resolved,
                                     reference_text=fv.raw_text)

    def _follow(self, start: str, points_to: dict[str, str | None],
                out: dict[str, FieldValue]) -> str | None:
        """Walk the reference chain to a field carrying a real value.

        Returns the field name that supplied the value, or None if the chain leaves
        the document, cycles, or ends on something with nothing in it.
        """
        seen_chain = {start}
        cur = points_to.get(start)
        for _ in range(MAX_HOPS):
            if cur is None or cur not in out:
                return None
            if cur in seen_chain:
                return None                      # cycle: A -> B -> A
            if cur not in points_to:             # a real value, not another pointer
                return cur if out[cur].normalised is not None else None
            seen_chain.add(cur)
            cur = points_to.get(cur)
        return None

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
