"""M05 — determine the real content type from bytes. Never trust the extension."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

PREFIX = 4096  # detection on a 200 MB file must not load 200 MB

MIME_TEXT = "text/plain"
MIME_PDF = "application/pdf"
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MIME_ZIP = "application/zip"
MIME_UNKNOWN = "application/octet-stream"

_BY_EXT = {".txt": MIME_TEXT, ".pdf": MIME_PDF, ".docx": MIME_DOCX, ".xlsx": MIME_XLSX}

_IMAGE_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"BM": "image/bmp",
}


@dataclass(frozen=True)
class Detection:
    mime:              str
    extension_claimed: str
    disagrees:         bool
    confidence:        float


def _zip_kind(data: bytes) -> str:
    """DOCX and XLSX are both ZIP — magic bytes are PK\\x03\\x04 for both, and a
    generic detector calls them both application/zip. Open the archive and look at
    the directory prefixes. This is the most common detection bug in this domain."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except (zipfile.BadZipFile, OSError):
        return MIME_ZIP
    if any(n.startswith("word/") for n in names):
        return MIME_DOCX
    if any(n.startswith("xl/") for n in names):
        return MIME_XLSX
    for n in names:
        if n == "[Content_Types].xml":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    body = z.read(n).decode("utf-8", "replace")
            except Exception:
                break
            if "wordprocessingml" in body:
                return MIME_DOCX
            if "spreadsheetml" in body:
                return MIME_XLSX
    return MIME_ZIP


def _sniff(data: bytes) -> tuple[str, float]:
    if not data:
        # A 0-byte file has no magic bytes. Handle it explicitly rather than letting
        # a None flow onward.
        return MIME_UNKNOWN, 0.0

    head = data[:PREFIX]
    for magic, mime in _IMAGE_MAGIC.items():
        if head.startswith(magic):
            return mime, 1.0
    if head.startswith(b"PK\x03\x04"):
        return _zip_kind(data), 0.95
    # PDFs with a BOM or leading whitespace before %PDF- exist in the wild, so scan
    # a bounded prefix rather than requiring offset 0.
    if b"%PDF-" in head[:1024]:
        return MIME_PDF, 1.0
    try:
        head.decode("utf-8")
        return MIME_TEXT, 0.8
    except UnicodeDecodeError:
        pass
    printable = sum(1 for b in head if 9 <= b <= 13 or 32 <= b <= 126)
    if printable / len(head) > 0.90:
        return MIME_TEXT, 0.6
    return MIME_UNKNOWN, 0.3


def detect(data: bytes, filename: str) -> Detection:
    claimed = Path(filename).suffix.lower()
    mime, confidence = _sniff(data)
    expected = _BY_EXT.get(claimed)
    # disagrees is a SIGNAL, recorded in the trace — never a failure. It may be the
    # planted wrong_doc_type case, or simply a customer whose export names files badly.
    disagrees = expected is not None and expected != mime
    return Detection(mime=mime, extension_claimed=claimed,
                     disagrees=disagrees, confidence=confidence)
