"""M06 — the extractor contract. bytes -> text, and no knowledge of shipping documents.

`ok` means exactly one thing: text came out. HARD RULE 7. The label check lives in
`route/confirm.py`, because v1.0's content-aware gate reported a readable
COMMERCIAL INVOICE as `unreadable` and the router's wrong_doc_type check never ran.
"""
from __future__ import annotations

import functools
import traceback
from typing import Protocol, runtime_checkable

from shipdoc.types import Block, ExtractedDoc, Method


@runtime_checkable
class Extractor(Protocol):
    mimes: tuple[str, ...]
    name: str
    version: str

    def extract(self, data: bytes, ref: str) -> ExtractedDoc: ...


def failed_doc(failure: str, *, method: Method = Method.NONE,
               mime: str = "application/octet-stream",
               warnings: tuple[str, ...] = ()) -> ExtractedDoc:
    """The single shape of every failure. T2 holds by construction."""
    return ExtractedDoc(ok=False, text="", blocks=(), method=method,
                        detected_mime=mime, warnings=warnings, failure=failure)


def _enforce(doc: object) -> ExtractedDoc:
    """Normalise a handler's return value so T2 cannot be violated downstream.

    A handler that reports success with empty text, or failure with text still
    attached, is corrected here rather than trusted.
    """
    if not isinstance(doc, ExtractedDoc):
        return failed_doc(f"handler returned {type(doc).__name__}, not ExtractedDoc")
    if doc.ok and not doc.text.strip():
        return failed_doc("handler reported ok with empty text",
                          method=doc.method, mime=doc.detected_mime,
                          warnings=doc.warnings)
    if not doc.ok and (doc.text != "" or doc.failure is None):
        return failed_doc(doc.failure or "handler failed without a reason",
                          method=doc.method, mime=doc.detected_mime,
                          warnings=doc.warnings)
    return doc


def never_raises(fn):
    """M06 contract 1. Converts any Exception into a failed ExtractedDoc.

    This is the second and only other broad `except Exception` in the system. It is
    mandated explicitly by M06 ("enforce with a decorator, not by asking each handler
    to remember"); unlike `run_stage` it is a type conversion, not a stage boundary.
    BaseException (KeyboardInterrupt, SystemExit) still propagates.
    """
    @functools.wraps(fn)
    def wrapper(self, data: bytes, ref: str) -> ExtractedDoc:
        try:
            return _enforce(fn(self, data, ref))
        except Exception as e:  # noqa: BLE001 — deliberate, see docstring
            return failed_doc(f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    return wrapper


def apply_gate(doc: ExtractedDoc, min_chars: int) -> ExtractedDoc:
    """M06 gate (v2): ok = len(text.strip()) >= min_extract_chars. Nothing else.

    Applied OUTSIDE the extraction cache (M15 P-GATE-CACHE): `ok` is the gate's
    verdict and the gate's input is config, so caching it would mean a threshold
    change has no effect until the cache is cleared by hand.
    """
    if not doc.ok:
        return doc
    if len(doc.text.strip()) < min_chars:
        return failed_doc("below_min_extract_chars", method=doc.method,
                          mime=doc.detected_mime, warnings=doc.warnings)
    return doc


__all__ = ["Extractor", "never_raises", "apply_gate", "failed_doc", "Block"]
