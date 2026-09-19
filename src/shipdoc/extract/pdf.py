"""M06 — PDF text layer.

Multi-column reading order scrambles label/value adjacency: a BL form with shipper on
the left and the BL number on the right extracts in the parser's order, not reading
order. So words are extracted with coordinates and lines are rebuilt by y-position
with an x-gap threshold.

This module does NOT decide whether a text layer is *useful* — that is
`route/confirm.py`'s job via the space-ratio check. `ok` means text came out.
"""
from __future__ import annotations

from shipdoc.detect.mime import MIME_PDF
from shipdoc.extract.base import failed_doc, never_raises
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef

Y_TOLERANCE = 3.0     # words within this many points share a line
X_GAP_SPACE = 1.2     # gap wider than this * median char width becomes a space


class PdfExtractor:
    mimes: tuple[str, ...] = (MIME_PDF,)
    name = "pdf"
    version = "2"

    def __init__(self, ocr_enabled: bool = False):
        self.ocr_enabled = ocr_enabled

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        import fitz  # imported here so `import shipdoc` works without pymupdf

        with fitz.open(stream=data, filetype="pdf") as doc:
            if doc.page_count == 0:
                return failed_doc("pdf_has_no_pages", method=Method.PDF_TEXT,
                                  mime=MIME_PDF)
            pages = [_page_lines(doc[i], i + 1) for i in range(doc.page_count)]
            has_images = any(doc[i].get_images() for i in range(doc.page_count))

        blocks: list[Block] = []
        lines: list[str] = []
        for page_no, page_lines in enumerate(pages, start=1):
            for text in page_lines:
                lines.append(text)
                blocks.append(Block(
                    text=text, kind="line",
                    ref=SourceRef(file=ref, locator=f"page {page_no} line {len(lines)}"),
                    confidence=1.0))

        text = "\n".join(lines)
        if not text.strip():
            # No text layer. Two genuinely different failures, distinguished by
            # whether the page carries a raster image — `pdfimages -list` confirmed
            # the split on this corpus and the decision rule applies both ways.
            if has_images:
                if self.ocr_enabled:
                    from shipdoc.extract.image import ImagePdfExtractor
                    return ImagePdfExtractor().extract(data, ref)
                return failed_doc("pdf_scanned_ocr_disabled", method=Method.PDF_TEXT,
                                  mime=MIME_PDF, warnings=("page_images_present",))
            # No text and no images: malformed or blank. OCR cannot help, and
            # `unreadable` is the correct answer rather than a thing to work around.
            return failed_doc("pdf_no_text_layer", method=Method.PDF_TEXT, mime=MIME_PDF)

        return ExtractedDoc(ok=True, text=text, blocks=tuple(blocks),
                            method=Method.PDF_TEXT, detected_mime=MIME_PDF,
                            warnings=(), failure=None)


def _page_lines(page, page_no: int) -> list[str]:
    """Rebuild reading order from word coordinates rather than trusting parser order."""
    words = page.get_text("words")      # (x0, y0, x1, y1, word, block, line, word_no)
    if not words:
        return []

    widths = [(w[2] - w[0]) / max(len(w[4]), 1) for w in words if w[4]]
    char_w = sorted(widths)[len(widths) // 2] if widths else 4.0

    rows: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: (round(w[1], 1), w[0])):
        for row in rows:
            if abs(row[0][1] - w[1]) <= Y_TOLERANCE:
                row.append(w)
                break
        else:
            rows.append([w])

    out: list[str] = []
    for row in rows:
        row.sort(key=lambda w: w[0])
        parts: list[str] = []
        prev_x1 = None
        for x0, _y0, x1, _y1, word, *_ in row:
            if prev_x1 is not None and (x0 - prev_x1) > X_GAP_SPACE * char_w:
                # A wide gap is a column break, which in these forms separates a
                # label from its value. Preserve it so the label matcher still works.
                parts.append(" ")
            parts.append(word)
            prev_x1 = x1
        line = " ".join(" ".join(parts).split())
        if line:
            out.append(line)
    return out
