"""M14 — the human-readable discrepancy report.

Required by v2 §1.1 and §6.1, but the v2 reorder dropped it from the build sequence
when pass 2 was deleted. It lands at stage 4, where real SI and BL values first exist
to put side by side.

The scoreboard cannot measure this output at all, which is exactly why it is the one
that gets forgotten — and it is the artifact that shows the behaviour the score
cannot see.
"""
from __future__ import annotations

from typing import Iterable

from shipdoc.types import Comparison, Record, RecordState, Verdict

_WIDTH = 78
_MARK = {Verdict.MATCH: "ok", Verdict.MISMATCH: "DEFECT", Verdict.CANNOT_DETERMINE: "??"}


def _truncate(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


class ReportAdapter:
    def emit(self, records: Iterable[Record]) -> str:
        records = list(records)
        interesting = [r for r in records
                       if r.defects or r.suspected or r.unresolved
                       or r.state is not RecordState.RESOLVED]
        lines: list[str] = []
        lines.append("=" * _WIDTH)
        lines.append("SHIPPING DOCUMENT VERIFICATION — DISCREPANCY REPORT")
        lines.append("=" * _WIDTH)
        lines.append(self._summary(records))
        lines.append("")

        for rec in interesting:
            lines.extend(self._record(rec))

        if not interesting:
            lines.append("No discrepancies and nothing escalated.")
        return "\n".join(lines) + "\n"

    def _summary(self, records: list[Record]) -> str:
        n = len(records)
        defect = sum(1 for r in records if r.defects)
        susp = sum(1 for r in records if r.suspected and not r.defects)
        esc = sum(1 for r in records if r.state is RecordState.ESCALATED)
        failed = sum(1 for r in records if r.state is RecordState.FAILED)
        return (f"{n} records · {defect} with confirmed defects · {susp} suspected only "
                f"· {esc} escalated · {failed} failed")

    def _record(self, rec: Record) -> list[str]:
        out = ["-" * _WIDTH,
               f"{rec.email_id}   category={rec.category}   state={rec.state}"]
        subject = _truncate(rec.raw.get("subject", ""), _WIDTH - 11)
        if subject:
            out.append(f"  subject: {subject}")
        if rec.reason is not None:
            out.append(f"  reason:  {rec.reason}")

        if rec.defects:
            out.append(f"  CONFIRMED DEFECTS: {', '.join(rec.defects)}")
        if rec.suspected:
            out.append(f"  SUSPECTED (below confidence bar): {', '.join(rec.suspected)}")
        if rec.unresolved:
            out.append(f"  UNRESOLVED: {', '.join(rec.unresolved)}")

        if rec.comparisons:
            out.append("")
            out.append(f"  {'field':<18} {'':<6} {'SI (authoritative)':<24} BL")
            for name, c in rec.comparisons.items():
                out.extend(self._comparison(name, c))
        out.append("")
        return out

    def _comparison(self, name: str, c: Comparison) -> list[str]:
        si = _truncate(c.si.raw_text if c.si else "—", 24)
        bl = _truncate(c.bl.raw_text if c.bl else "—", 24)
        mark = _MARK.get(c.verdict, "?")
        if c.verdict is Verdict.CANNOT_DETERMINE and c.leaning is Verdict.MISMATCH:
            mark = "??->X"
        rows = [f"  {name:<18} {mark:<6} {si:<24} {bl}"]
        if c.verdict is not Verdict.MATCH and c.detail:
            rows.append(f"  {'':<18} {'':<6} {_truncate(c.detail, 48)}")
        if c.si is not None and c.verdict is not Verdict.MATCH:
            rows.append(f"  {'':<18} {'':<6} SI@{c.si.source.locator}"
                        + (f"  BL@{c.bl.source.locator}" if c.bl else ""))
        return rows
