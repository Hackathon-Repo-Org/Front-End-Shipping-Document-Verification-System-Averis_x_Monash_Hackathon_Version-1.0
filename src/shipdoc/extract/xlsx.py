"""M06 — Excel. Four classic bugs, all of them guarded here.

The fourth is the one v1.0 actively recommended: "stop after N consecutive empty
rows" silently drops every field below a spacer row, which is exactly how a partial
field map is produced. This module bounds by max_row AND a hard cap, and never
terminates early on blank rows.
"""
from __future__ import annotations

import io

from shipdoc.detect.mime import MIME_XLSX
from shipdoc.extract.base import failed_doc, never_raises
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef

HARD_ROW_CAP = 2000       # ws.max_row can report 1048576 for an 8-row sheet
HARD_COL_CAP = 64


class XlsxExtractor:
    mimes: tuple[str, ...] = (MIME_XLSX,)
    name = "xlsx"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        from openpyxl import load_workbook

        # data_only=True, or a weight cell returns "=SUM(B2:B9)" instead of a number.
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=False)
        try:
            lines: list[str] = []
            blocks: list[Block] = []
            # All sheets. wb.active silently ignores sheets 2..n.
            for ws in wb.worksheets:
                merged = _merged_lookup(ws)
                n_rows = min(ws.max_row or 0, HARD_ROW_CAP)
                n_cols = min(ws.max_column or 0, HARD_COL_CAP)
                for r in range(1, n_rows + 1):
                    cells = []
                    first_addr = None
                    for c in range(1, n_cols + 1):
                        value = _cell_value(ws, r, c, merged)
                        if value:
                            cells.append(value)
                            first_addr = first_addr or f"{ws.title}!{ws.cell(r, c).coordinate}"
                    if not cells:
                        continue        # skip the ROW, never stop the scan
                    # Label and value sit in adjacent cells, not separated by a colon
                    # on one line. Flattening lets the text label matcher apply
                    # unmodified; the cell address is kept in Block.ref, which is why
                    # SourceRef.locator is a string and not a line number.
                    line = " | ".join(cells)
                    lines.append(line)
                    blocks.append(Block(text=line, kind="cell",
                                        ref=SourceRef(file=ref, locator=first_addr or ws.title),
                                        confidence=1.0))
        finally:
            wb.close()

        text = "\n".join(lines)
        if not text.strip():
            return failed_doc("xlsx_no_cell_text", method=Method.XLSX_CELL, mime=MIME_XLSX)
        return ExtractedDoc(ok=True, text=text, blocks=tuple(blocks),
                            method=Method.XLSX_CELL, detected_mime=MIME_XLSX,
                            warnings=(), failure=None)


def _merged_lookup(ws) -> dict[tuple[int, int], tuple[int, int]]:
    """Merged cells carry their value in the top-left only; every other cell in the
    range reads None. A label spanning three columns would orphan its value."""
    out: dict[tuple[int, int], tuple[int, int]] = {}
    for rng in ws.merged_cells.ranges:
        anchor = (rng.min_row, rng.min_col)
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                out[(r, c)] = anchor
    return out


def _cell_value(ws, r: int, c: int, merged: dict) -> str:
    anchor = merged.get((r, c))
    if anchor is not None and anchor != (r, c):
        return ""            # already emitted at the anchor
    rr, cc = anchor or (r, c)
    v = ws.cell(rr, cc).value
    if v is None:
        return ""
    return str(v).strip()
