"""M06 — the terminal tier. Always the last handler, and it always fails closed.

Built before any format handler (M06: retrofitting the contract across five handlers
that each invented their own error behaviour is the expensive path).
"""
from __future__ import annotations

from shipdoc.extract.base import failed_doc, never_raises
from shipdoc.types import ExtractedDoc, Method


class TerminalExtractor:
    """Handles anything no other extractor claimed. Never raises, never succeeds."""

    mimes: tuple[str, ...] = ("*",)
    name = "terminal"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        return failed_doc("no_handler_for_mime", method=Method.NONE,
                          warnings=("terminal_tier",))
