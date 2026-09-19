"""M06 — MIME to handler, with the terminal tier as the guaranteed last resort."""
from __future__ import annotations

from shipdoc.extract.base import Extractor, apply_gate
from shipdoc.extract.terminal import TerminalExtractor
from shipdoc.types import ExtractedDoc


class ExtractorRegistry:
    def __init__(self):
        self._by_mime: dict[str, Extractor] = {}
        self._terminal = TerminalExtractor()

    def register(self, ex: Extractor) -> None:
        for mime in ex.mimes:
            self._by_mime[mime] = ex

    def for_mime(self, mime: str) -> Extractor:
        """Unhandled input falls to the terminal tier — never a crash, never a skip."""
        return self._by_mime.get(mime, self._terminal)

    def extract(self, data: bytes, ref: str, mime: str, min_chars: int,
                cache=None) -> ExtractedDoc:
        """Extract, then gate. The gate is applied OUTSIDE the cache (M15
        P-GATE-CACHE): `ok` is the gate's verdict and the gate's input is config, so
        caching a gated result would mean a threshold change has no effect until a
        manual clear."""
        ex = self.for_mime(mime)
        name = getattr(ex, "name", type(ex).__name__)
        version = getattr(ex, "version", "0")

        doc = cache.get(data, name, version, ref) if cache is not None else None
        if doc is None:
            doc = ex.extract(data, ref)
            if cache is not None:
                cache.put(data, name, version, doc)
        return apply_gate(doc, min_chars)


def default_registry(ocr_enabled: bool = False) -> ExtractorRegistry:
    """Handlers are added here as they are built.

    A handler whose optional dependency is missing is SKIPPED, not imported. Its
    formats then fall to the terminal tier and become `unreadable` — degraded, with
    a reason, rather than an ImportError at startup. `python -m shipdoc doctor`
    reports which handlers are live.
    """
    from shipdoc.extract.text import TextExtractor
    from shipdoc.infra import capabilities as caps

    r = ExtractorRegistry()
    r.register(TextExtractor())          # stdlib only, always available

    if caps.have_pdf():
        from shipdoc.extract.pdf import PdfExtractor
        r.register(PdfExtractor(ocr_enabled=ocr_enabled))
    if caps.have_xlsx():
        from shipdoc.extract.xlsx import XlsxExtractor
        r.register(XlsxExtractor())
    if caps.have_docx():
        from shipdoc.extract.docx import DocxExtractor
        r.register(DocxExtractor())
    return r
