"""M06 — Word.

`doc.paragraphs` does NOT include text inside tables. A BL rendered as a table
returns zero paragraphs and looks empty — the classic python-docx bug. Tables are
iterated separately and recursively, and text boxes are walked out of the XML.
"""
from __future__ import annotations

import io
import zipfile

from shipdoc.detect.mime import MIME_DOCX
from shipdoc.extract.base import failed_doc, never_raises
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxExtractor:
    mimes: tuple[str, ...] = (MIME_DOCX,)
    name = "docx"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        import docx

        d = docx.Document(io.BytesIO(data))

        lines: list[str] = []
        blocks: list[Block] = []
        method = Method.DOCX_PARA

        for para in d.paragraphs:
            t = para.text.strip()
            if t:
                lines.append(t)
                blocks.append(Block(t, "paragraph",
                                    SourceRef(ref, f"paragraph {len(lines)}"), 1.0))

        table_lines = []
        for ti, table in enumerate(d.tables, start=1):
            table_lines.extend(_table_lines(table, ti))
        if table_lines:
            method = Method.DOCX_TABLE if not lines else method
            for locator, line in table_lines:
                lines.append(line)
                blocks.append(Block(line, "cell", SourceRef(ref, locator), 1.0))

        for t in _textbox_lines(d):
            lines.append(t)
            blocks.append(Block(t, "region", SourceRef(ref, "textbox"), 1.0))

        text = "\n".join(lines)
        if not text.strip():
            # A .docx containing only a pasted screenshot has no paragraphs and no
            # tables. Say so specifically, so the reason is not mistaken for a
            # corrupt file.
            if _has_media(data):
                return failed_doc("docx_image_only_needs_ocr",
                                  method=Method.DOCX_PARA, mime=MIME_DOCX,
                                  warnings=("word_media_present",))
            return failed_doc("docx_no_text", method=Method.DOCX_PARA, mime=MIME_DOCX)

        return ExtractedDoc(ok=True, text=text, blocks=tuple(blocks),
                            method=method, detected_mime=MIME_DOCX,
                            warnings=(), failure=None)


def _table_lines(table, ti: int, depth: int = 0) -> list[tuple[str, str]]:
    """Rows flattened the same way xlsx rows are, so one label matcher serves both.
    Nested tables are recursed, not skipped."""
    out: list[tuple[str, str]] = []
    if depth > 4:
        return out
    for ri, row in enumerate(table.rows, start=1):
        cells = []
        for cell in row.cells:
            t = cell.text.strip()
            if t and t not in cells:      # merged cells repeat their text
                cells.append(t)
            for nested in cell.tables:
                out.extend(_table_lines(nested, ti, depth + 1))
        if cells:
            out.append((f"table {ti} row {ri}", " | ".join(cells)))
    return out


def _textbox_lines(d) -> list[str]:
    """Headers, footers and text boxes are in neither paragraphs nor tables; text
    boxes live in w:txbxContent."""
    out: list[str] = []
    try:
        for node in d.element.body.iter(f"{_W_NS}txbxContent"):
            for para in node.iter(f"{_W_NS}p"):
                t = "".join(n.text or "" for n in para.iter(f"{_W_NS}t")).strip()
                if t:
                    out.append(t)
    except Exception:
        return out
    return out


def _has_media(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return any(n.startswith("word/media/") for n in z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
