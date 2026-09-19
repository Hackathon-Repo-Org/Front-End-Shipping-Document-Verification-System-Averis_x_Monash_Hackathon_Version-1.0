# SPEC V2 PATCH 01

**Read alongside `ARCHITECTURE_SPEC_V2.md`. Where they overlap, this file wins.**

Raised by Stage 0 pre-flight (items 1–4) plus three further gaps found on re-reading (5–7).
All seven are specification gaps, not implementation choices.

---

## 1. Stage 2 gate — scoring is deferred, not abandoned

**The finding is correct.** The static ZIP bundle contains no `docker-compose.yml`, no
Dockerfile and no server URL. `loader.Inbox.submit()` requires an HTTP source. The brief
offers two access options and the scoring endpoint exists only on the **local server (Docker)**
option — the ZIP is data only. That was always true; the spec simply assumed the server option
had been taken.

**Resolution — the Stage 2 gate becomes:**

```
PASS when:
  - submission.json has exactly 520 keys
  - every key is an email_id present in inbox/
  - every entry has exactly the 5 fields of sample_submission.json,
    with values drawn only from the permitted sets
  - a strict schema check passes against sample_submission.json's shape
  - `python -m shipdoc --submit` fails cleanly with a readable message
    when no server URL is configured (it must not crash)
Score: n/a — record "baseline: not measured"
```

**Do not let this block the build.** Wiring the scoreboard later is one configuration line:
`Inbox("http://localhost:8080")` in place of `Inbox("data")`. The adapter, the submission
writer and the CLI are unchanged.

**But go and get the Docker bundle.** Stage 2 exists to produce a number that every later stage
is measured against. Without it you are building blind: you will not know whether Stage 3
helped, and Stage 3 is predicted to be the largest single movement in the score. If the
challenge organisers publish a Docker bundle or a compose file separately, fetch it before
Stage 3 rather than after.

---

## 2. Missing type definitions — `Method`, `StageEvent`, `Decision`

**Correct.** `Method` was defined in v1.0 §4 and lost in the v2 rewrite. `StageEvent` and
`Decision` were referenced in both versions and defined in neither. Add to `types.py`:

```python
class Method(StrEnum):
    NATIVE_TEXT = "native_text"   # plain .txt read
    PDF_TEXT    = "pdf_text"      # PDF text layer
    DOCX_PARA   = "docx_para"
    DOCX_TABLE  = "docx_table"
    XLSX_CELL   = "xlsx_cell"
    OCR         = "ocr"
    NONE        = "none"          # extraction produced nothing

@dataclass(frozen=True)
class StageEvent:
    stage:   str                  # "classify" | "route" | "extract" | ...
    outcome: str                  # "ok" | "escalated" | "failed"
    detail:  str = ""             # exception text, or a short note
    seq:     int = 0              # monotonic within a record; ordering only

@dataclass(frozen=True)
class Decision:
    email_id: str
    field:    str                 # the field this decision resolves
    verdict:  Verdict             # what the human concluded
    note:     str = ""            # why — shown in the report
    by:       str = ""            # reviewer identifier
    at:       str = ""            # ISO-8601 timestamp
```

`StageEvent.seq` rather than a wall-clock timestamp: a timestamp would make two runs over
identical input differ, breaking I6 for no benefit. **Nothing in `trace` may carry wall-clock
time or a random id.**

Also add the three config sub-objects `Config` refers to:

```python
@dataclass(frozen=True)
class Thresholds:
    min_extract_chars:   int = 120
    min_labels_present:  int = 2      # used by route/confirm, NOT by extract
    pdf_space_ratio_min: float = 0.08 # below this, a PDF text layer is broken
    quantity_epsilon:    Decimal = Decimal("0.5")

@dataclass(frozen=True)
class LLMSettings:
    model:          str
    prompt_version: str
    timeout_s:      float = 30.0
    temperature:    float = 0.0
    seed:           int | None = 0

@dataclass(frozen=True)
class FeatureFlags:
    ocr_enabled:     bool = False
    parallel_workers: int = 1
```

---

## 3. `FieldSpec` is missing two attributes its own config uses

**Not raised in pre-flight — found on re-reading.** Appendix A's `fields.yaml` sets
`address_bearing: true` and `extract: '(\d+)\s*x\s*\d+'`, but §M01's `FieldSpec` declares
neither. `load_config` would either drop them silently or raise.

```python
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
    address_bearing: bool = False          # ADDED — M10 P-ADDRESS
    extract_pattern: str | None = None     # ADDED — yaml key `extract`
```

`address_bearing: true` selects the looser threshold pair. Put both threshold sets in
`pipeline.yaml` rather than repeating numbers per field:

```yaml
thresholds:
  name_strict:  { threshold: 0.98, grey_low: 0.85 }
  name_address: { threshold: 0.92, grey_low: 0.75 }
```

**These numbers are a starting point, not a result.** Spec Open Item 8 requires measuring
grey-band volume before tuning them.

---

## 4. `process()` signature and `_halted`

**Correct.** `decisions` was a free variable and `_escalated` was never defined.

```python
def process(rec: Record, cfg: Config, llm: LLMClient | None,
            decisions: Mapping[tuple[str, str], Decision]) -> Record:
    ...

def _halted(rec: Record) -> bool:
    """True iff a stage escalated or failed.

    Exact, and it depends on HARD RULE 4: before `evaluate` runs, the only
    writer of `state` is `run_stage`. If that ever stops being true, this
    function becomes silently wrong — so assert the rule, do not trust it.
    """
    return rec.state is not None
```

The proposed `rec.state is not None` is right. It is renamed `_halted` because `_escalated`
reads as "escalated specifically" and the predicate also covers `FAILED`.

**Add a test for the rule this depends on:** grep the source for assignments to `.state` and
assert exactly two sites — `state/machine.py` and `pipeline.run_stage`.

---

## 5. Internal reason keys must not be string-identical to external ones

**The finding is correct, and it is the same defect this spec diagnosed in v1.0's I5** — a
check that fires on benign code. The proposed fix (scope the grep to assignment sites) treats
the symptom. The cause is that the internal vocabulary was given the external spellings, which
makes `reason_map.py` an identity function pretending to be a translation.

**They are genuinely different vocabularies.** The internal set is richer: v2 already maps
`classification_conflict` to `missing_value`, which is not 1:1. Give the internal set its own
names and the boundary becomes real rather than cosmetic.

In `errors.py`:

```python
class ReasonKey(StrEnum):
    ERR_NO_ATTACHMENT = "err_no_attachment"
    ERR_BAD_DOC_TYPE  = "err_bad_doc_type"
    ERR_UNREADABLE    = "err_unreadable"
    ERR_NO_VALUE      = "err_no_value"
    ERR_CLASSIFY      = "err_classify"
    ERR_UNHANDLED     = "err_unhandled"

_FOR_EXCEPTION: dict[type[BaseException], ReasonKey] = {
    MissingAttachmentError: ReasonKey.ERR_NO_ATTACHMENT,
    DocumentTypeError:      ReasonKey.ERR_BAD_DOC_TYPE,
    ExtractionError:        ReasonKey.ERR_UNREADABLE,
    IngestError:            ReasonKey.ERR_UNREADABLE,
    MissingValueError:      ReasonKey.ERR_NO_VALUE,
    ClassificationConflict: ReasonKey.ERR_CLASSIFY,
}

def reason_key(e: BaseException) -> ReasonKey:
    return _FOR_EXCEPTION.get(type(e), ReasonKey.ERR_UNHANDLED)
```

> `reason_key()` was referenced in §M13's `run_stage` and never defined. That is gap 6.

In `adapters/reason_map.py` — **the only place the external strings appear:**

```python
REVIEW_REASON: dict[ReasonKey, str] = {
    ReasonKey.ERR_NO_ATTACHMENT: "missing_attachment",
    ReasonKey.ERR_BAD_DOC_TYPE:  "wrong_doc_type",
    ReasonKey.ERR_UNREADABLE:    "unreadable",
    ReasonKey.ERR_NO_VALUE:      "missing_value",
    ReasonKey.ERR_CLASSIFY:      "missing_value",   # deliberately not 1:1
    ReasonKey.ERR_UNHANDLED:     "unreadable",
}
```

`Record.reason` now holds a `ReasonKey`, not a string. In `state/machine.py`, replace the
string literals:

```python
raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_CLASSIFY)   # was "classification_conflict"
raise_state(rec, RecordState.ESCALATED, ReasonKey.ERR_NO_VALUE)   # was "missing_value"
```

**I5's grep is now green and meaningful:**

```
grep -rE '"(OK|MISMATCH|NEEDS_REVIEW|missing_attachment|wrong_doc_type|unreadable|missing_value)"' \
     src/ --exclude-dir=adapters      # must be empty
```

`email_id` and the category strings are **out of scope for I5** — v2 §7 already narrowed it to
status values, review_reason values and submission key names. Use exactly the pattern above.

---

## 6. `reason_key()` was undefined

Covered by §5 above. It is referenced in §M13 `run_stage` and now lives in `errors.py`.

---

## 7. Unqualified enum members in §M11

The `evaluate` listing uses bare `MISMATCH` and `CANNOT_DETERMINE`. Qualify them —
`Verdict.MISMATCH`, `Verdict.CANNOT_DETERMINE` — or import the members explicitly. Cosmetic,
but it is the function that carries the system's central invariant and it should read exactly.

---

## 8. Model selection for M07

`qwen2.5vl` is a vision-language model. It will work for classification, but vision-tuned
models are generally weaker at strict instruction-following than an instruct-tuned sibling, and
M07's hard requirement is that the output is **exactly one of five strings**.

**Recommended:** pull a small instruct model for M07 (`qwen2.5:7b-instruct` or similar) and
keep `qwen2.5vl` in reserve for Stage 7, where a vision model is one of the three options
alongside Tesseract and corrupt-file handling.

Either way, M07's hard rule stands: validate the returned string against the five permitted
values, retry once, then return `None`. **Never accept free text.** If the instruct model is
not available, proceed with `qwen2.5vl` and record the choice — the validation makes a weaker
model safe, just less accurate.

---

## 9. Dependencies — approved

`pip install rapidfuzz pytest`

`rapidfuzz` is named in §M10. `pytest` was an omission in the spec's dependency list — every
stage gate is expressed as tests, so it is required. Nothing else is approved without asking.

`pdfimages`, `pdftotext` and `tesseract` are already present, which means all three Stage 7
options are open. Do not choose between them until Stage 7's pre-flight has run.

---

## Summary of changes to apply

| # | Change | File |
|---|---|---|
| 1 | Stage 2 gate drops the score requirement | build process |
| 2 | Add `Method`, `StageEvent`, `Decision`, `Thresholds`, `LLMSettings`, `FeatureFlags` | `types.py` |
| 3 | `FieldSpec` gains `address_bearing`, `extract_pattern`; threshold pairs move to `pipeline.yaml` | `types.py`, `config/` |
| 4 | `process()` takes `decisions`; `_halted()` defined; add the two-assignment-site test | `pipeline.py` |
| 5 | `ReasonKey` enum; internal keys renamed; `REVIEW_REASON` in adapters | `errors.py`, `adapters/reason_map.py` |
| 6 | `reason_key()` defined | `errors.py` |
| 7 | Qualify enum members in `evaluate` | `state/machine.py` |
| 8 | Prefer an instruct model for M07 | `pipeline.yaml` |
| 9 | `rapidfuzz`, `pytest` approved | environment |

*End of patch 01.*
