"""Stage 1 gate — M06 extractor contract.

The contract is the whole point: no extractor raises, and `not ok` implies empty
text plus a failure reason (T2). It is enforced by a decorator, never by trusting
a handler to remember.
"""
import random

import pytest

from shipdoc.extract.base import apply_gate, never_raises
from shipdoc.extract.terminal import TerminalExtractor
from shipdoc.types import ExtractedDoc, Method

TERMINAL = TerminalExtractor()


def check_contract(doc: ExtractedDoc) -> None:
    """T2, asserted on every result regardless of how it was produced."""
    assert isinstance(doc, ExtractedDoc)
    if not doc.ok:
        assert doc.text == "", "T2: not ok implies empty text"
        assert doc.failure is not None, "T2: not ok implies a failure reason"
    else:
        assert doc.text.strip() != "", "ok must never mean empty text"
        assert doc.failure is None
    assert isinstance(doc.method, Method)
    assert isinstance(doc.blocks, tuple)
    assert isinstance(doc.warnings, tuple)


# --------------------------------------------------------------------------
# Fuzz the terminal tier
# --------------------------------------------------------------------------

def test_terminal_on_empty_bytes():
    check_contract(TERMINAL.extract(b"", "empty.bin"))


def test_terminal_on_ten_megabytes_of_zeros():
    doc = TERMINAL.extract(b"\x00" * (10 * 1024 * 1024), "zeros.bin")
    check_contract(doc)
    assert not doc.ok


@pytest.mark.parametrize("seed", range(40))
def test_terminal_on_random_bytes(seed):
    rnd = random.Random(seed)
    data = bytes(rnd.getrandbits(8) for _ in range(rnd.randint(0, 4096)))
    check_contract(TERMINAL.extract(data, f"fuzz_{seed}.bin"))


# A valid PNG magic header followed by bytes that are not valid image data.
# FIXED, NOT RANDOM: pytest derives the test id from the parameter's repr, so
# os.urandom here regenerated the id on every collection and made the suite
# non-reproducible — the same reason StageEvent carries `seq` and not a timestamp.
# The descending byte ramp is obviously synthetic so nobody mistakes it for a
# captured fixture. Do not put the randomness back; test_terminal_on_random_bytes
# already fuzzes, and it seeds its RNG.
PNG_HEADER_THEN_GARBAGE = b"\x89PNG\r\n\x1a\n" + bytes(range(255, 127, -1))


@pytest.mark.parametrize("data", [
    b"",
    b"\x00",
    b"\xff\xfe\xfd",
    b"%PDF-1.4 truncated",
    b"PK\x03\x04" + b"\x00" * 64,
    "日本語のテキスト".encode("utf-8"),
    PNG_HEADER_THEN_GARBAGE,
])
def test_terminal_on_adversarial_inputs(data):
    check_contract(TERMINAL.extract(data, "adversarial.bin"))


def test_terminal_always_fails_closed():
    """The terminal tier is the last resort: it never claims success."""
    doc = TERMINAL.extract(b"plenty of perfectly readable text " * 100, "x.txt")
    assert not doc.ok
    assert doc.method is Method.NONE
    check_contract(doc)


# --------------------------------------------------------------------------
# The decorator, not the handler, is what makes the contract true
# --------------------------------------------------------------------------

class ExplodingExtractor:
    mimes = ("application/x-explode",)
    name = "exploding"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        raise RuntimeError("handler blew up")


class LyingExtractor:
    """Claims success while returning nothing — contract violation 2."""
    mimes = ("application/x-lie",)
    name = "lying"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        return ExtractedDoc(ok=True, text="   ", blocks=(), method=Method.NATIVE_TEXT,
                            detected_mime="text/plain", warnings=(), failure=None)


class DirtyFailureExtractor:
    """Fails but leaves text behind — T2 violation."""
    mimes = ("application/x-dirty",)
    name = "dirty"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str) -> ExtractedDoc:
        return ExtractedDoc(ok=False, text="leftover", blocks=(), method=Method.NONE,
                            detected_mime="text/plain", warnings=(), failure=None)


class WrongTypeExtractor:
    mimes = ("application/x-wrong",)
    name = "wrong"
    version = "1"

    @never_raises
    def extract(self, data: bytes, ref: str):
        return "not an ExtractedDoc"


@pytest.mark.parametrize("ex", [
    ExplodingExtractor(), LyingExtractor(), DirtyFailureExtractor(), WrongTypeExtractor(),
])
def test_decorator_enforces_the_contract(ex):
    doc = ex.extract(b"whatever", "ref.bin")
    check_contract(doc)
    assert not doc.ok


def test_decorator_records_the_exception_text():
    doc = ExplodingExtractor().extract(b"", "ref.bin")
    assert doc.failure is not None
    assert "RuntimeError" in doc.failure


def test_decorator_does_not_swallow_keyboard_interrupt():
    """BaseException must still propagate — we convert errors, not signals."""
    class Interrupting:
        @never_raises
        def extract(self, data, ref):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        Interrupting().extract(b"", "ref")


# --------------------------------------------------------------------------
# The gate: `ok` means "text came out" and NOTHING about content (HARD RULE 7)
# --------------------------------------------------------------------------

def _doc(text: str) -> ExtractedDoc:
    return ExtractedDoc(ok=True, text=text, blocks=(), method=Method.NATIVE_TEXT,
                        detected_mime="text/plain", warnings=(), failure=None)


def test_gate_passes_on_enough_characters():
    doc = apply_gate(_doc("x" * 200), min_chars=120)
    assert doc.ok
    check_contract(doc)


def test_gate_fails_below_the_threshold():
    doc = apply_gate(_doc("x" * 10), min_chars=120)
    assert not doc.ok
    check_contract(doc)


def test_gate_ignores_content_entirely():
    """A COMMERCIAL INVOICE has zero shipping labels and must still pass the gate.
    v1.0 failed it here and reported `unreadable` instead of `wrong_doc_type`.
    The label check belongs to route/confirm, not to extract."""
    invoice = ("COMMERCIAL INVOICE\nInvoice No.: 5250078266\nSeller: APRIL FINE PAPER\n"
               "Buyer: KPP-ANTALIS\nIncoterms: FOB\n" * 3)
    doc = apply_gate(_doc(invoice), min_chars=120)
    assert doc.ok, "extract/ must have no opinion about document content"


def test_gate_counts_stripped_length():
    doc = apply_gate(_doc("   " + "x" * 5 + "   \n\n"), min_chars=120)
    assert not doc.ok
