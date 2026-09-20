"""M02 — data structures only. No behaviour, no runtime imports from other shipdoc modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Mapping


class ReasonKey(StrEnum):
    """The INTERNAL reason vocabulary. Deliberately does not share spellings with the
    external `review_reason` values — `adapters/reason_map.py` performs a real
    translation, not an identity function wearing a boundary's clothes.

    Lives here rather than in errors.py because it is a data vocabulary, not an error,
    and `types` is the bottom layer every module may import.
    """
    ERR_NO_ATTACHMENT = "err_no_attachment"
    ERR_BAD_DOC_TYPE  = "err_bad_doc_type"
    ERR_UNREADABLE    = "err_unreadable"
    ERR_NO_VALUE      = "err_no_value"
    ERR_CLASSIFY      = "err_classify"
    ERR_UNHANDLED     = "err_unhandled"


class Category(StrEnum):
    BL_COMPARISON = "BL_COMPARISON"
    SI_REQUEST    = "SI_REQUEST"
    INVOICE_QUERY = "INVOICE_QUERY"
    GENERAL       = "GENERAL"
    SPAM          = "SPAM"


class Method(StrEnum):
    NATIVE_TEXT = "native_text"
    PDF_TEXT    = "pdf_text"
    DOCX_PARA   = "docx_para"
    DOCX_TABLE  = "docx_table"
    XLSX_CELL   = "xlsx_cell"
    OCR         = "ocr"
    NONE        = "none"


class Verdict(StrEnum):
    MATCH            = "match"
    MISMATCH         = "mismatch"
    CANNOT_DETERMINE = "cannot_determine"


class RecordState(StrEnum):
    RESOLVED  = "resolved"
    ESCALATED = "escalated"
    FAILED    = "failed"


STATE_PRECEDENCE: Mapping[RecordState, int] = {
    RecordState.RESOLVED:  0,
    RecordState.ESCALATED: 1,
    RecordState.FAILED:    2,
}

# The comparator type names config may use. M01 says to validate against
# `comparators.COMPARATORS`, but that is an upward import from the bottom layer.
# Vocabulary lives here; conformance is asserted at the top.
#
# TODO(stage 4): compare/comparators.py MUST assert
#     set(COMPARATORS) == FIELD_TYPES
# at import time. Without it the two can drift and config validation silently
# permits a type no comparator implements.
FIELD_TYPES: frozenset[str] = frozenset({"text", "port", "integer", "quantity"})


@dataclass(frozen=True)
class SourceRef:
    file:    str
    locator: str
    span:    tuple[int, int] | None = None


@dataclass(frozen=True)
class Block:
    text:       str
    kind:       str
    ref:        SourceRef
    confidence: float = 1.0


@dataclass(frozen=True)
class ExtractedDoc:
    ok:            bool
    text:          str
    blocks:        tuple[Block, ...]
    method:        Method
    detected_mime: str
    warnings:      tuple[str, ...]
    failure:       str | None


@dataclass(frozen=True)
class FieldValue:
    field:      str
    raw_text:   str
    normalised: str | Decimal | int | None
    source:     SourceRef
    method:     Method
    label_seen: str
    # Phase 10. Set when this value was not read from its own line but SUBSTITUTED
    # from another field on the same document, because the document said
    # `SAME AS CONSIGNEE` or carried a ditto mark. It names the field the value came
    # from. A reviewer must be able to see that the system supplied a value rather
    # than read one.
    #
    # When this is set, `raw_text` holds the SUBSTITUTED value and `reference_text`
    # holds the pointer as the document actually wrote it. The substitution is made
    # in `raw_text` rather than only in `normalised` because the party comparator
    # re-derives the company name and address from `raw_text` — resolving one and not
    # the other leaves the two comparator families disagreeing about what the value
    # is, which is precisely the class of bug this field exists to avoid.
    resolved_from:  str | None = None
    reference_text: str | None = None


@dataclass(frozen=True)
class Comparison:
    field:    str
    verdict:  Verdict
    si:       FieldValue | None
    bl:       FieldValue | None
    strategy: str
    detail:   str
    # Patch 02 §3. Set ONLY when verdict is CANNOT_DETERMINE and the comparator had a
    # directional signal. `None` means "I have no view" — the honest state for anything
    # that failed to obtain data, and it projects to NEEDS_REVIEW rather than to a
    # fabricated defect.
    leaning:  Verdict | None = None


@dataclass(frozen=True)
class StageEvent:
    stage:   str
    outcome: str
    detail:  str = ""
    seq:     int = 0


@dataclass(frozen=True)
class Decision:
    email_id: str
    field:    str
    verdict:  Verdict
    note:     str = ""
    by:       str = ""
    at:       str = ""


@dataclass
class Record:
    """The only mutable type. `state` has no default — HARD RULE 1."""
    email_id:    str
    raw:         dict
    category:    str | None = None
    documents:   dict[str, ExtractedDoc] = field(default_factory=dict)
    fields:      dict[str, dict[str, FieldValue]] = field(default_factory=dict)
    # Phase 10. {role: set of field names whose LABEL was matched in that document},
    # recorded independently of whether a usable value came out. The difference
    # between "we found no gross-weight label in this BL" and "the BL leaves gross
    # weight blank" is the whole of Fix 1, and it is exactly what a reviewer needs on
    # screen before deciding. `inspect` renders it; a UI would too.
    labels_seen: dict[str, frozenset[str]] = field(default_factory=dict)
    comparisons: dict[str, Comparison] = field(default_factory=dict)
    state:       RecordState | None = None
    reason:      ReasonKey | None = None
    defects:     list[str] = field(default_factory=list)
    unresolved:  list[str] = field(default_factory=list)
    # Patch 02 §3: fields whose verdict is CANNOT_DETERMINE but whose leaning is
    # MISMATCH — the system formed a view and fell below its own confidence bar.
    suspected:   list[str] = field(default_factory=list)
    # A comparison request whose documents have not been sent YET. Nothing is missing
    # and there is nothing to review — it resolves clean and stays out of the queue,
    # visible under its own filter. See classify/intent.py.
    awaiting_docs: bool = False
    trace:       list[StageEvent] = field(default_factory=list)


# ---------------------------------------------------------------- config types

@dataclass(frozen=True)
class FieldSpec:
    name:            str
    type:            str
    required:        bool
    synonyms:        tuple[str, ...]
    anti_synonyms:   tuple[str, ...] = ()
    threshold:       float | None = None
    grey_low:        float | None = None
    unit:            str | None = None
    conversions:     Mapping[str, Decimal] = field(default_factory=dict)
    address_bearing: bool = False
    extract_pattern: str | None = None


@dataclass(frozen=True)
class ThresholdPair:
    threshold: float
    grey_low:  float


@dataclass(frozen=True)
class Thresholds:
    min_extract_chars:   int = 120
    min_labels_present:  int = 2
    pdf_space_ratio_min: float = 0.08
    quantity_epsilon:    Decimal = Decimal("0.5")
    name_strict:         ThresholdPair = ThresholdPair(0.98, 0.85)
    name_address:        ThresholdPair = ThresholdPair(0.92, 0.75)


@dataclass(frozen=True)
class LLMSettings:
    model:          str
    prompt_version: str
    timeout_s:      float = 30.0
    temperature:    float = 0.0
    seed:           int | None = 0


@dataclass(frozen=True)
class FeatureFlags:
    ocr_enabled:      bool = False
    parallel_workers: int = 1
    # Patch 02 §5 A/B. True: an SI/BL attachment pair decides the category and the
    # model may not overturn it. False: the model may overturn a structural verdict.
    structural_decisive: bool = True
    # Phase 5 UN/LOCODE port resolution. DEFAULT OFF, pending measurement against the
    # answer key. Off means the port comparator takes the pre-Phase-5 code path
    # exactly — the resolver is simply not passed to it. The code and the data file
    # are retained so the question "does this help?" can be answered by flipping this
    # one boolean, rather than by rewriting anything.
    port_resolution_enabled: bool = False


@dataclass(frozen=True)
class Config:
    fields:              Mapping[str, FieldSpec]
    comparison_category: str
    sentinels:           tuple[str, ...]
    thresholds:          Thresholds
    llm:                 LLMSettings
    flags:               FeatureFlags
    # Reference data, resolved relative to the config directory. None when the file
    # is not configured or not present — the resolver degrades rather than failing.
    unlocode_path:       object | None = None
