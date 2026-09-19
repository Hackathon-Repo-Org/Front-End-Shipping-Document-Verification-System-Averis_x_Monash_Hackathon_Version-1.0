"""M06 — OCR for PDFs whose pages are embedded raster images.

Stage-7 pre-flight (`pdfimages -list`) split the five unreadable PDFs into two
genuinely different failures, so the decision rule applies BOTH ways:

  email_512/513/514 (SI+BL, ~21 KB)  one 1240x1754 rgb image at 150 ppi per page
                                     -> a scan. OCR is the right answer.
  email_511/515 (BL only, ~770 B)    zero images; pdfimages reports
                                     "Couldn't find trailer dictionary" and
                                     "Illegal character in hex string"
                                     -> malformed, not scanned. No OCR can help.
                                     `unreadable` IS the correct answer and this
                                     module must not pretend otherwise.

Per-word confidence is retained into Block.confidence: it is the only surviving
consumer of confidence in v2, and an OCR extractor that discards it has thrown away
its main value.
"""
from __future__ import annotations

import shutil

from shipdoc.detect.mime import MIME_PDF
from shipdoc.extract.base import failed_doc, never_raises
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef

RENDER_DPI = 200
MIN_WORD_CONFIDENCE = 30.0     # tesseract reports 0-100; below this is noise


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


class ImagePdfExtractor:
    """Not registered by MIME — the PDF handler delegates here when a PDF turns out
    to have no text layer but does carry page images."""

    mimes: tuple[str, ...] = ()
    name = "ocr"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        import fitz
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return failed_doc("ocr_dependency_missing", method=Method.OCR, mime=MIME_PDF)
        if not tesseract_available():
            return failed_doc("ocr_binary_missing", method=Method.OCR, mime=MIME_PDF)

        import io

        lines: list[str] = []
        blocks: list[Block] = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page_no in range(doc.page_count):
                pix = doc[page_no].get_pixmap(dpi=RENDER_DPI)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                d = pytesseract.image_to_data(
                    img, output_type=pytesseract.Output.DICT)
                lines.extend(_lines_from_tsv(d, ref, page_no + 1, blocks))

        text = "\n".join(lines)
        if not text.strip():
            return failed_doc("ocr_produced_no_text", method=Method.OCR, mime=MIME_PDF)
        return ExtractedDoc(ok=True, text=text, blocks=tuple(blocks),
                            method=Method.OCR, detected_mime=MIME_PDF,
                            warnings=("ocr",), failure=None)


def _lines_from_tsv(d: dict, ref: str, page_no: int, blocks: list[Block]) -> list[str]:
    """Group words into lines using tesseract's own block/par/line numbering, and
    carry the mean per-word confidence onto each Block."""
    rows: dict[tuple, list[tuple[str, float]]] = {}
    for i, word in enumerate(d["text"]):
        word = (word or "").strip()
        if not word:
            continue
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < MIN_WORD_CONFIDENCE:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        rows.setdefault(key, []).append((word, conf))

    out: list[str] = []
    for key in sorted(rows):
        words = rows[key]
        line = " ".join(w for w, _ in words)
        mean_conf = sum(c for _, c in words) / len(words) / 100.0
        out.append(line)
        blocks.append(Block(text=line, kind="line",
                            ref=SourceRef(ref, f"page {page_no} line {key[2]}"),
                            confidence=round(mean_conf, 3)))
    return out
