"""M06 — plain text. The simplest handler, and the one 192 of 250 attachments use."""
from __future__ import annotations

from shipdoc.extract.base import never_raises
from shipdoc.detect.mime import MIME_TEXT
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef

_ENCODINGS = ("utf-8", "utf-8-sig", "cp1252", "latin-1")


class TextExtractor:
    mimes: tuple[str, ...] = (MIME_TEXT,)
    name = "text"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        text, encoding = _decode(data)
        lines = text.splitlines()
        blocks = tuple(
            Block(text=line, kind="line",
                  ref=SourceRef(file=ref, locator=f"line {i}"), confidence=1.0)
            for i, line in enumerate(lines, start=1) if line.strip()
        )
        warnings = () if encoding == "utf-8" else (f"decoded_as_{encoding}",)
        return ExtractedDoc(ok=True, text=text, blocks=blocks,
                            method=Method.NATIVE_TEXT, detected_mime=MIME_TEXT,
                            warnings=warnings, failure=None)


def _decode(data: bytes) -> tuple[str, str]:
    """Decoding belongs to the extractor, which knows the format — M04 keeps the
    loader on read_bytes precisely so this choice is made here and made once."""
    for enc in _ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "utf-8-replace"
