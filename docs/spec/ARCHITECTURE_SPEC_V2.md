# TECHNICAL SPECIFICATION — Shipping Document Verification

**Version** 2.0 · **Supersedes** v1.0 · **Status** Corrected after adversarial review

---

## 0. Changes from v1.0

v1.0 was reviewed against the actual dataset and **its central correctness claim was false**.
This version fixes that and 30 other findings. Appendix C carries the full disposition.

### The fatal defect in v1.0

v1.0 §5.11 defined `RESOLVED` as:

```
RESOLVED ⟺ category decided AND (category != BL_COMPARISON
                                 OR all 7 comparisons ∈ {MATCH, MISMATCH})
```

The right disjunct quantifies over `record.comparisons`, whose cardinality nothing constrained.
**`all([])` is `True` in Python.** Any path reaching `evaluate` with an empty or partial
comparison map therefore asserted `RESOLVED`, and M14 projected that to `status: OK`.

`email_507` has one attachment. M08 raises `MissingAttachmentError`, `run_stage` sets
`ESCALATED`, §6.1 has no short-circuit, `evaluate` runs and overwrites it with `RESOLVED`,
and the record is reported clean. v1.0 §8's own golden test demanded `NEEDS_REVIEW` for that
record — **the specification contradicted itself.**

This was not an implementation hazard. A faithful implementation of the written rule produces
the wrong answer.

### The five structural fixes

| # | Fix | Replaces |
|---|---|---|
| 1 | `evaluate` asserts **cardinality** against the field registry; it does not quantify over the dict it was handed | v1.0 §5.11 rule |
| 2 | States are **monotone and ordered**: `FAILED > ESCALATED > RESOLVED`; `evaluate` may never downgrade | v1.0's conflicting `⟺` / `⟸` |
| 3 | M10 emits **exactly `len(cfg.fields)` comparisons**, `CANNOT_DETERMINE` for anything absent | v1.0's unspecified loop driver |
| 4 | Missing values in this corpus are **non-empty strings** (`N/A`, `_______`, `TBA`); they are mapped to `None` before a `FieldValue` exists | v1.0's `None`-only guard |
| 5 | The label check moves **out of `extract/` and into the router**; `ok=False` means "no text came out", nothing else | v1.0's quality gate |

### Other significant changes

- **Pass 2 is deleted.** It loaded an artifact nothing wrote. Re-running pass 1 with decisions
  as input achieves the same thing, and the extraction cache makes it cheap.
- **Invariant I5 is narrowed.** The five category strings are simultaneously the domain
  vocabulary and the external schema; no adapter can hide that. I5 now covers only `status`
  values, `review_reason` values, and submission key names — which are genuinely adapter-owned,
  and which makes the CI check green rather than permanently red.
- **A confirmed `MISMATCH` now outranks `CANNOT_DETERMINE`.** v1.0 discarded a detected defect
  when any other field was unreadable. §5.11 states the cost of this change.
- **OCR moves from stage 8 to stage 7 and is no longer optional.** 8 of 28 PDFs have no usable
  text layer, affecting 5 comparison emails. v1.0 §1.3 was wrong.
- **Format handlers are sequenced by unlocked comparisons, not file count.** The `.docx` handler
  alone unlocks **zero** comparisons — all 8 `.docx` files are paired with `.xlsx`.
- **Semantic classification moves to stage 3.** 394 of 520 records (76%) are decided entirely by
  `classify/`, and the structural layer by design cannot decide them.
- **The comparator registry is deleted** in favour of a module-level dict.
- **`pipeline.py` (M13) is specified.** v1.0 had no module owning orchestration.

---

## 1. Scope

### 1.1 In scope

Batch processing of a fixed email corpus (520 records, 250 attachments) producing:

1. A category for **every** email, from a fixed set of five.
2. For document-comparison requests, a seven-field comparison of a Shipping Instruction (SI)
   against a draft Bill of Lading (BL), **with the SI as the authoritative reference**.
3. A submission conforming to a fixed external schema.
4. A human-readable discrepancy report.
5. A review queue for records the system could not decide, carrying source evidence.

### 1.2 Explicit non-goals

| Non-goal | Reason |
|---|---|
| Real-time processing | Batch domain with a human review pause. |
| Automatic amendment of the BL | A BL is a document of title. Amending it is a legal act. |
| A user interface | CLI plus queue file. Would sit above the adapter boundary. |
| A database | Files on disk survive runs, need no setup, are readable during a demo. |
| Multi-user workflow | Single team inbox. |
| Cross-script name **matching** | Needs transliteration/entity resolution — a new component. |

> **Do not over-read the last row.** It excludes comparing *values* across scripts. It does
> **not** excuse ignoring non-ASCII **labels**: `Gross Weight毛重(KGS):` is a real label on a
> compared field in this corpus. See M09 P-CJK.

### 1.3 Corpus characteristics — corrected

| Property | Value |
|---|---|
| Email records | 520, one JSON file each |
| Attachments | 250, `attachments/email_<NNN>_<SI\|BL>.<ext>` |
| Formats | `.txt` 192 · `.pdf` 28 · `.xlsx` 22 · `.docx` 8 |
| Emails with 2 / 1 / 0 attachments | 124 / 2 / 394 |
| **PDFs with no usable text layer** | **8 of 28** — `511_BL`, `515_BL` (0 chars); `512/513/514` SI+BL (1 char) |
| **Affected comparison emails** | **5** — `email_511` … `email_515` |
| Planted wrong-document files | 5 — one `COMMERCIAL INVOICE`, two `CERTIFICATE OF ORIGIN`, two `PACKING LIST`, all named `_BL.txt` |
| Null sentinels in values | `_______ MTS` ×4, `N/A` ×2, `TBA` ×1 |
| Distinct labels across 192 `.txt` | 64 |
| Filename convention exceptions | 0 |

**Comparison pairs by format** — this drives the build order, not file count:

| Pair | Emails | Unlocked by |
|---|---|---|
| `txt` + `txt` | 94 | text handler alone |
| `pdf` + `pdf` | 13 | pdf handler |
| `docx` + `xlsx` | 8 | **both** — docx alone unlocks nothing |
| `xlsx` + `xlsx` | 7 | xlsx handler |
| `pdf` + `txt` | 2 | pdf handler |

> The architecture must still not **assume** these hold. They determine sequencing, not shape.
> v1.0 stated this rule and then violated it by gating OCR on a 3-file sample.

---

## 2. System context

```
   ┌──────────────┐        ┌───────────────────────────────┐       ┌──────────────┐
   │  Dataset     │        │  shipdoc                      │       │  Scoreboard  │
   │  ZIP or HTTP │───────▶│   single pass                 │──────▶│  POST /submit│
   └──────────────┘ loader │   decisions applied at start  │ adapt └──────────────┘
                           │                               │
                           │   review_queue.json ──────────┼──────▶ human reviewer
                           │            ▲                  │              │
                           └────────────┼──────────────────┘              │
                                        └──── decision: field filled ─────┘
                                             (same file, re-read next run)
```

There is **one pass**. Human decisions are read at the start of every run. Re-running is the
merge mechanism; the extraction cache makes it cheap.

---

## 3. Module map

```
shipdoc/
├── config/
│   ├── fields.yaml            # field registry — the 7 fields as DATA
│   ├── pipeline.yaml          # thresholds, sentinels, model, flags
│   └── unlocode.csv
│
├── src/shipdoc/
│   ├── cli.py                 # M16  argv only
│   ├── pipeline.py            # M13  orchestration  [NEW in v2]
│   ├── config.py              # M01
│   ├── types.py               # M02  data only
│   ├── errors.py              # M03  exception types ONLY  [changed]
│   │
│   ├── ingest/loader_port.py  # M04
│   ├── detect/mime.py         # M05
│   │
│   ├── extract/               # M06  bytes → text. No domain knowledge.
│   │   ├── base.py registry.py terminal.py
│   │   ├── text.py pdf.py docx.py xlsx.py image.py
│   │
│   ├── classify/              # M07
│   │   ├── structural.py semantic.py arbiter.py
│   │
│   ├── route/                 # M08  [split in v2]
│   │   ├── by_name.py         #      before extraction
│   │   └── confirm.py         #      after extraction — owns the label check
│   │
│   ├── normalise/             # M09
│   │   ├── labels.py values.py ports.py verify.py sentinels.py
│   │
│   ├── compare/               # M10  module-level dict, no registry class
│   │   ├── comparators.py
│   │
│   ├── state/machine.py       # M11  the ONLY writer of Record.state
│   ├── review/queue.py        # M12
│   ├── llm/                   # M12b
│   ├── adapters/              # M14  owns the external vocabulary
│   │   ├── submission.py report.py reason_map.py
│   └── infra/                 # M15
```

**Dependency rule.** `adapters` → `llm` → `review` → `state` → `compare` → `normalise` →
`route/confirm` → `extract` → `detect` → `ingest` → `classify` → `infra` → `config` →
`errors` → `types`. No module imports leftward. `types`, `errors`, `config`, `infra` are
the foundation and are importable by anyone.

`pipeline.py` sits above everything and imports freely; `cli.py` imports only `pipeline`.

> **v2.1 corrections.** The chain above previously omitted `infra` and `classify`
> entirely, so neither had a stated position and the rule could not be checked for them.
> `infra` joins the foundation (it imports nothing else from the package); `classify`
> sits just above it, importing only `types` and `errors`.
>
> **`route` no longer depends on `normalise`.** `confirm_doc_type(docs, cfg, index)`
> takes its label index as a **mandatory** injected argument and declares the shape it
> needs locally (`route/confirm.py:LabelMatcher`). `pipeline.py` — which legitimately
> sits above both — constructs it once per run and injects it. Previously the index
> defaulted to a freshly built `LabelIndex(cfg)`, which forced a leftward import.
>
> **`KNOWN_VIOLATIONS` is empty** as of this phase. The rule is enforced by
> `tests/property/test_layering.py`, which parses every module with `ast`. A
> `TYPE_CHECKING`-guarded import **counts as a violation**: the rule protects the
> architecture, not the runtime, and such an import is one keystroke from becoming real.

---

## 4. Core data types

```python
class Verdict(StrEnum):
    MATCH            = "match"
    MISMATCH         = "mismatch"
    CANNOT_DETERMINE = "cannot_determine"

class RecordState(StrEnum):
    RESOLVED  = "resolved"      # precedence 0
    ESCALATED = "escalated"     # precedence 1
    FAILED    = "failed"        # precedence 2

STATE_PRECEDENCE = {RecordState.RESOLVED: 0,
                    RecordState.ESCALATED: 1,
                    RecordState.FAILED: 2}

@dataclass(frozen=True)
class SourceRef:
    file: str; locator: str; span: tuple[int,int] | None

@dataclass(frozen=True)
class Block:
    text: str; kind: str; ref: SourceRef
    confidence: float          # 1.0 native; OCR word confidence otherwise

@dataclass(frozen=True)
class ExtractedDoc:
    ok:            bool        # ok == "text came out", NOTHING about content
    text:          str         # "" iff not ok
    blocks:        tuple[Block,...]
    method:        Method
    detected_mime: str
    warnings:      tuple[str,...]
    failure:       str | None  # set iff not ok

@dataclass(frozen=True)
class FieldValue:
    field: str
    raw_text:   str
    normalised: str | Decimal | int | None   # None iff a sentinel was matched
    source: SourceRef
    method: Method
    label_seen: str

@dataclass(frozen=True)
class Comparison:
    field: str
    verdict: Verdict
    si: FieldValue | None
    bl: FieldValue | None
    strategy: str
    detail: str

@dataclass
class Record:                      # the ONLY mutable type
    email_id:    str
    raw:         dict
    category:    str | None = None
    documents:   dict[str, ExtractedDoc] = field(default_factory=dict)
    fields:      dict[str, dict[str, FieldValue]] = field(default_factory=dict)
    comparisons: dict[str, Comparison] = field(default_factory=dict)
    state:       RecordState | None = None
    reason:      str | None = None          # internal reason key, NOT schema string
    defects:     list[str] = field(default_factory=list)
    unresolved:  list[str] = field(default_factory=list)
    trace:       list[StageEvent] = field(default_factory=list)
```

### Type invariants

| # | Invariant | Enforced by |
|---|---|---|
| **T1** | `Record.state is not None` at pipeline exit | M13, asserted |
| **T2** | `not ok ⟹ text == "" and failure is not None` | M06 decorator |
| **T3** | `FieldValue.raw_text` appears in **`ExtractedDoc.text`** | M09 `verify.py` |
| **T4** | `len(record.comparisons) == len(cfg.fields)` whenever `category` is the comparison category **and** no earlier stage escalated | M10 contract |
| **T5** | `FieldValue.normalised is None` ⟺ the raw text matched a configured sentinel | M09 `sentinels.py` |

> **T3 changed in v2.** v1.0 verified against "the source file". For the 22 `.xlsx` (flattened
> rows) and multi-column PDFs (reconstructed by y-position), there is no source text to verify
> against — the reconstruction *is* the canonical form. T3 now verifies **extraction fidelity**,
> not source fidelity, and that is what it was always actually able to do.

---

## 5. Module specifications

### M01 · `config.py`

Loads `fields.yaml` / `pipeline.yaml` into frozen typed objects.

```python
class FieldSpec:
    name: str
    type: str                     # "text"|"port"|"integer"|"quantity"
    required: bool
    synonyms: tuple[str,...]      # positive, matched longest-first
    anti_synonyms: tuple[str,...] # NEW in v2 — see M09 P-NET
    threshold: float | None       # per-field, NEW in v2
    grey_low: float | None
    unit: str | None
    conversions: Mapping[str,Decimal]

class Config:
    fields: Mapping[str, FieldSpec]
    comparison_category: str      # the one category that triggers comparison
    sentinels: tuple[str,...]     # NEW in v2 — regex list
    thresholds: Thresholds
    llm: LLMSettings
```

> **v2 change — `strategy` is deleted.** v1.0 carried both `type` and `strategy` and used them
> interchangeably. A field's `type` selects its comparator. One key.

**PITFALLS**
- Validate at load: every `type` must exist in `comparators.COMPARATORS`. One line,
  `set(f.type for f in fields) <= COMPARATORS.keys()`.
- Config is frozen and **passed explicitly**. No module-level singleton — `evaluate` needs it
  (see M11) and a hidden global is how that dependency gets smuggled in.
- No silent defaults. A missing threshold raises.

---

### M02 · `types.py`

Data only. No behaviour. No imports from other `shipdoc` modules.
`Record` is mutable; everything else is frozen.

---

### M03 · `errors.py`

> **v2 change.** v1.0 mapped exceptions to the four external `review_reason` strings *inline*,
> in the innermost most-imported module — which pushed the external schema into every module by
> design. The mapping now lives in `adapters/reason_map.py`, keyed by exception **type**.
> The exception says *what went wrong*; the adapter says *what to call it*.

```python
class ShipdocError(Exception): ...
class ConfigError(ShipdocError): ...            # startup, fatal
class IngestError(ShipdocError): ...
class ExtractionError(ShipdocError): ...
class DocumentTypeError(ShipdocError): ...
class MissingAttachmentError(ShipdocError): ...
class MissingValueError(ShipdocError): ...
class ClassificationConflict(ShipdocError): ... # NEW in v2 — see M07
class LLMUnavailable(ShipdocError): ...         # degraded mode, NOT fatal
```

**PITFALLS**
- `LLMUnavailable` must not be fatal. It triggers §8.
- Do not catch `Exception` broadly except in `run_stage` (M13).

---

### M04 · `ingest/loader_port.py`

```python
class InboxPort(Protocol):
    def emails(self) -> Iterator[dict]: ...
    def read_bytes(self, path: str) -> bytes: ...
    def submit(self, payload: dict) -> dict: ...
```

**PITFALLS**
- **Always `read_bytes()`, never `read_text()`.** 58 of 250 attachments are binary, and the
  supplied loader decodes with `errors="replace"` — so the failure is **silent mojibake**, not
  an exception. Decoding belongs to the extractor, which knows the format.
- Do not let `loader.Inbox` types leak past this module, or unit tests need the dataset.
- Sort by `email_id` before processing — `emails()` ordering is not guaranteed stable.
- A network source can fail mid-iteration. Retry, then **assert the final count**.

---

### M05 · `detect/mime.py`

```python
@dataclass(frozen=True)
class Detection:
    mime: str; extension_claimed: str; disagrees: bool; confidence: float
```

**PITFALLS**
- **`.docx` and `.xlsx` are both ZIP** (`PK\x03\x04`). A generic detector says
  `application/zip` for both. Open the archive and check `word/` vs `xl/`, or read
  `[Content_Types].xml`. Most common detection bug in this domain.
- A 0-byte file has no magic bytes — handle `None` explicitly, route to terminal.
- PDFs with a BOM or leading whitespace before `%PDF-` exist. Scan the first 1024 bytes.
- `disagrees=True` is a **signal**, recorded in `trace`; never a failure.
- Read a bounded prefix only.

---

### M06 · `extract/`

**Responsibility: bytes → text. It has no knowledge of shipping documents.**

> **v2 change (fixes C4 and K4).** v1.0's quality gate required *"at least 2 known labels from
> the field registry"* to set `ok=True`. Three verified consequences:
> 1. `email_501_BL.txt` is a `COMMERCIAL INVOICE` — perfectly readable, 0 shipping labels —
>    so v1.0 reported it `unreadable` instead of `wrong_doc_type`, and the router's content
>    check never ran.
> 2. The gate was inconsistent across the planted set: `PACKING LIST` files cleared it,
>    `CERTIFICATE OF ORIGIN` files did not.
> 3. It made `extract/` depend on the field registry, which `normalise/` owns — a leftward
>    import the dependency rule forbids.
>
> **`ok` now means exactly one thing: text came out.** The label check moved to `route/confirm.py`.

```python
class Extractor(Protocol):
    mimes: tuple[str, ...]
    def extract(self, data: bytes, ref: str) -> ExtractedDoc: ...   # MUST NOT raise
```

**Contract**
1. Never raises. Enforce with a **decorator** on every `extract()` — not by asking each handler
   to remember.
2. Never returns `ok=True` with empty text.
3. Same structure regardless of format or outcome.
4. Always records `method`.
5. Unhandled input → terminal tier → `ok=False`, never a crash, never a skip.

**Gate (v2):** `ok = len(text.strip()) >= cfg.thresholds.min_extract_chars`. Nothing else.

#### PITFALLS — general
- **The timeout mitigation is platform-dependent.** `signal.SIGALRM` does not exist on Windows,
  and a thread-based timeout cannot interrupt a C extension spinning inside `pdfminer` or
  `openpyxl` — it returns control while the worker keeps burning CPU, so the batch is not
  bounded. The only mitigation that works is `ProcessPoolExecutor` with a per-task timeout and a
  killed worker. **That changes this contract**: `bytes` in and `ExtractedDoc` out must both be
  picklable. Accept that, or drop the timeout and accept the hang risk explicitly. Do not
  pretend a thread timer solves it.
- Build `terminal.py` and the gate **before** any format handler.

#### PITFALLS — `pdf.py`
- **A text layer can be present but useless** — some PDFs extract with no spaces
  (`SHIPPERGLOBALRUBBER`). Character count alone passes them. Since the label check has moved
  out of this module, the **router** is now responsible for catching this. Say so in the
  handover, or it falls between the two.
- **Multi-column reading order** scrambles label/value adjacency. Extract per-word with
  coordinates and rebuild lines by y-position with an x-gap threshold.
- **8 of 28 PDFs in this corpus have no usable text layer.** Two size profiles:
  `511_BL`/`515_BL` at ~770 bytes are too small to hold a raster image — likely blank or
  malformed, needing corrupt-file handling, not OCR. `512/513/514` at ~21 KB look like embedded
  raster. **Run `pdfimages -list` on both groups before committing to Tesseract.**

#### PITFALLS — `docx.py`
- **`doc.paragraphs` excludes text inside tables.** A BL rendered as a table returns zero
  paragraphs and looks empty. Iterate `doc.tables` separately, nested tables recursively.
- Headers, footers and text boxes are in neither; text boxes live in `w:txbxContent`.
- Empty document ⇒ check `word/media/` for a pasted screenshot; route those bytes to the image
  handler.

#### PITFALLS — `xlsx.py`
- `load_workbook(data_only=True)` or a weight cell returns `"=SUM(B2:B9)"`.
- **Merged cells** carry the value in the top-left only; resolve `ws.merged_cells.ranges` first.
- **`ws.max_row` is inflated by stray formatting** — can report 1048576 for an 8-row sheet.
  Bound the iteration.
- **The "stop after N consecutive empty rows" mitigation silently drops fields below a spacer
  row.** v1.0 recommended it and it is the mechanism that produced a partial field map. Bound by
  `max_row` *and* a hard cap; do **not** terminate on blank rows. If you must, raise a warning
  and let M10's cardinality contract catch the consequence.
- Flatten each row to `" | ".join(cells)` so the text label matcher applies; keep the cell
  address in `Block.ref`.
- **All sheets**, not just `wb.active`.

#### PITFALLS — `image.py`
- **No longer a stub.** 5 comparison emails need this or corrupt-file handling.
- Retain per-word confidence into `Block.confidence` — it is the only surviving consumer of
  confidence in v2.

---

### M07 · `classify/`

```python
def classify(record: Record, cfg: Config,
             llm: LLMClient | None) -> tuple[str | None, float]
    # category is None  ⟺  the arbiter could not decide
    # or raises ClassificationConflict
```

> **v2 change (fixes C6/B2).** v1.0 returned `tuple[str, float]`, which has **no channel to
> express escalation** — yet v1.0 §6.1 said *"conflict ⇒ ESCALATED"*. The three ways an
> implementer could have resolved that were all wrong: raise an undocumented type, invent a
> sentinel category that then flows into the output as a real category, or mutate `record`
> behind the declared signature.

| Layer | Input | Decides |
|---|---|---|
| `structural` | attachment count + names | partitions 126 |
| `semantic` | subject + body | the 394 with no attachments |
| `arbiter` | both | conflict ⇒ `None` / raise |

**PITFALLS**
- **Zero attachments does not imply "not a comparison request."** A request with the files
  forgotten is still the comparison category, with `missing_attachment`. The structural layer
  **partitions**; it does not decide the 394.
- **Never classify on the subject line alone.** Structural evidence outranks text.
- **Constrain the model to the five exact strings.** Anything else: one retry, then `None`.
- Truncate the body — subject plus ~1500 chars. Signatures are most of the token cost.
- **Cache key must include the prompt-template hash**, or a prompt change silently reuses old
  answers.
- Do not classify on the sender domain.
- **76% of the corpus is decided here and nowhere else.** This module carries more of the score
  than M08–M10 combined.

---

### M08 · `route/` — split in v2

> **v2 change (fixes B1).** v1.0's `route(record, docs: dict[str, ExtractedDoc])` required
> extracted documents, but §6.1 ran `route` **before** extraction. The signature and the flow
> contradicted each other. Split into two functions at two positions.

```python
# route/by_name.py  — runs BEFORE extraction
def route_by_name(record: Record) -> dict[str, str]
    # {"SI": path, "BL": path}
    # raises MissingAttachmentError  (cheap — no extraction needed)

# route/confirm.py  — runs AFTER extraction; owns the label check
def confirm_doc_type(docs: dict[str, ExtractedDoc], cfg: Config) -> None
    # raises DocumentTypeError
```

**PITFALLS — `by_name.py`**
- **Bind the filename's number to the record.** The regex `email_(\d+)_(SI|BL)\.(\w+)$` captures
  the number; v1.0 discarded it. Assert it equals `record.email_id`'s number. 0 instances in
  this corpus — it is a one-line assertion guarding a catastrophic failure (comparing the wrong
  pair of documents, confidently).
- **Two attachments can collide on the dict key.** `email_012_BL.txt` + `email_012_BL_v2.txt`
  both parse to `"BL"`; one silently vanishes, then `docs["SI"]` raises `KeyError` → `FAILED` →
  the wrong reason. Assert `len(parsed) == len(set(roles))`. 0 instances currently; cheapest
  possible check.
- Case-insensitive, anchored at the end of the stem. Decide the `_BL_final` question and write
  it down.

**PITFALLS — `confirm.py`**
- **This module owns the "is it the right kind of document" question**, moved here from
  `extract/`. It has the field registry available; `extract/` does not and should not.
- A readable document with too few shipping labels is `DocumentTypeError` → `wrong_doc_type`,
  **not** `unreadable`. Five planted files depend on this distinction.
- A document with plenty of characters but no recognisable labels may also be a **broken PDF
  text layer** (`SHIPPERGLOBALRUBBER`). Distinguish: if `method == PDF_TEXT` and the text has an
  abnormally low space ratio, that is `unreadable`, not `wrong_doc_type`.
- If both documents look like the same type, **escalate — do not pick one.** Guessing inverts
  the reference direction and the system confidently reports the customer's own SI needs fixing.

---

### M09 · `normalise/`

| File | Job |
|---|---|
| `sentinels.py` | **NEW in v2** — raw text → `None` when it is a null placeholder |
| `labels.py` | label → canonical field name |
| `values.py` | raw value → typed value |
| `ports.py` | port string → resolved identity |
| `verify.py` | T3 |

#### `sentinels.py` — new, and it closes the most likely silent-pass path

> **v2 change (fixes C5/P1).** v1.0 guarded `None` thoroughly and was emphatic that two missing
> values must never compare `MATCH`. **The guard was on the wrong representation.** In this
> corpus a missing value is a non-empty string:
> ```
> Gross Weight毛重(KGS): N/A
> NET WEIGHT: _______ MTS
> ```
> Verified: `_______ MTS` ×4, `N/A` ×2, `TBA` ×1. Both sides carrying `"N/A"` are equal under
> `==`, pass `verify.py` (the string *is* in the source), and reach the comparator as
> well-formed values.

```yaml
sentinels:            # config, regex, case-insensitive, after strip
  - '^n/?a$'
  - '^tba$'
  - '^tbd$'
  - '^nil$'
  - '^-+$'
  - '^_+$'
  - '^$'
```

A match sets `FieldValue.normalised = None` **before** the value reaches a comparator (T5).
`raw_text` is preserved for the evidence trail.

**PITFALL:** strip trailing unit tokens before testing — `_______ MTS` must match `^_+$` after
the unit is removed, or it will not fire.

**PITFALL:** **forbid the identity short-circuit.** `if si.raw == bl.raw: return MATCH` is the
single most tempting optimisation in the comparator and it re-opens this hole completely.

#### `labels.py`

**PITFALLS**
- **Match longest label first** — `Port of Loading:` ×42 vs `Port of Loading (POL):` ×35
  both occur; matching the shorter leaves `(POL):` in the value.
- **P-NET — but longest-match points the wrong way for weight.** Verified counts:
  `GROSS WEIGHT` ×45, `Gross Wt (kgs)` ×50, `Gross Weight (KG)` ×41, **`NET WEIGHT` ×5**.
  The compared field is gross weight. Any substring match on "weight" captures the net weight,
  and `email_516_SI.txt` has **both** — gross is `N/A`, net is `_______ MTS`. A matcher
  preferring the longer or later label compares **net against gross**.
  **This needs `anti_synonyms` (a negative list), not just a longest-match rule.**
- **P-CJK — a required label contains CJK.** `Gross Weight毛重(KGS):` is verified in this corpus.
  §1.2's cross-script non-goal is about *values*; ignoring non-ASCII here turns a present field
  into `missing_value`. Normalise by stripping non-ASCII **before** synonym lookup, and put the
  stripped form in the map.
- **Value termination** ends at the next recognised label, a blank line, or N lines. Write the
  rule down.
- **Harvest synonyms from observed labels.** Verified: 64 distinct labels across 192 files,
  including `To the Order of` ×37 for consignee and `Consignee (Non-Negotiable)` ×52 —
  neither of which anyone would invent.
- **The model maps labels only, never values.** Given a value it will "correct" `Sdn Bhd` to
  `Sendirian Berhad` on one document and not the other, and the deterministic comparator will
  faithfully report a mismatch that does not exist.

#### `values.py`

**PITFALLS**
- `Decimal`, never `float`.
- Thousands vs decimal separator is ambiguous (`1,234`). Pick a rule, and **record the
  interpretation in `Comparison.detail`** so a reviewer can see what was assumed.
- `MT` / `T` / `TON` are not synonyms: 1000 / 907.18 / 1016.05 kg. Unrecognised unit ⇒
  `normalised = None` ⇒ `CANNOT_DETERMINE`. **A parse failure must not bubble as an exception** —
  v1.0 left this unstated and it is the difference between `FAILED` and `CANNOT_DETERMINE`.
- **Container count: extract the count, not the size.** 38 distinct forms verified
  (`1 x 40'HC`, `6 x 20'GP`, `15 x 40'HC`, …). A naive "first integer" works on all of them.
- **P-MULTISIZE:** a shipment written `2 x 40'HC + 1 x 20'GP` has no representation as an
  integer — summing gives `3`, which compares `MATCH` against `3 x 40'HC`, a **different
  shipment**. 0 instances in this corpus. Guard: any count string containing `+` or two size
  tokens ⇒ `CANNOT_DETERMINE`, never a silent sum.
- Normalise both documents with **the same function object**.

#### `ports.py`

**PITFALLS**
- A regex recognises the *shape* `^[A-Z]{2}[A-Z2-9]{3}$`; it cannot resolve `CNSHA` to Shanghai.
  That needs the UN/LOCODE dataset.
- UN/LOCODE has duplicate names. Resolve code → name; never name → code.
- Strip **known country tokens** only — a blanket "drop after the comma" destroys
  `Port Klang, Selangor`.
- Unresolvable code ⇒ `CANNOT_DETERMINE`, never a mismatch.

#### `verify.py`

**PITFALLS**
- Normalise whitespace on both sides, or a value wrapped across two lines fails verification and
  escalates a good field.
- Verify against **`ExtractedDoc.text`** (T3 as revised), not the original bytes.
- Failure ⇒ the value was invented ⇒ `CANNOT_DETERMINE`. Do **not** keep it at lower confidence.

---

### M10 · `compare/comparators.py`

> **v2 change 1 (fixes C2).** v1.0 never said **who drives the loop**. Iterating the SI keys, or
> the intersection of SI and BL keys — both natural readings — means a field absent from both is
> never passed to a comparator at all, and the `None` guard cannot help: it protects against a
> present-but-empty value, not an absent key.
>
> **v2 change 2 (§6 of the review).** The registry class is deleted. Four types, three functions,
> all known at design time — a module-level dict is the same guarantee with less ceremony.

```python
COMPARATORS: dict[str, Callable] = {
    "text": cmp_text, "port": cmp_port,
    "integer": cmp_numeric, "quantity": cmp_numeric,
}

def compare_all(si: dict[str, FieldValue],
                bl: dict[str, FieldValue],
                cfg: Config) -> dict[str, Comparison]:
    """CONTRACT: returns exactly len(cfg.fields) entries.
       Iterates the REGISTRY, never the input maps."""
    return {name: COMPARATORS[spec.type](si.get(name), bl.get(name), spec)
            for name, spec in cfg.fields.items()}
```

**Verdict rules**

| Situation | Verdict | Why |
|---|---|---|
| both present, equal / above threshold | `MATCH` | |
| both present, below `grey_low` | `MISMATCH` | |
| both present, **in the grey band** | **`CANNOT_DETERMINE`** | v1.0 said "decide + log" and never said which way. See below. |
| **SI present, BL absent or `None`** | **`MISMATCH`** | the SI is authoritative — the BL omitted what the shipper instructed |
| SI absent or `None` | `CANNOT_DETERMINE` | no reference to compare against |
| both absent | `CANNOT_DETERMINE` | never `MATCH` |

> **v2 change 3 (fixes P8).** v1.0's text row said *"between ⇒ decide + log"* — the most
> load-bearing undefined phrase in the document. Grey → `MATCH` defeats the system's purpose in
> one branch; grey → `MISMATCH` floods the false-alarm channel the brief penalises. It is
> `CANNOT_DETERMINE`.
>
> **v2 change 4 (fixes P6).** §1.1 declares the SI authoritative, but v1.0's comparators treated
> `si=None` and `bl=None` identically. A field the shipper specified and the carrier omitted is
> a **defect**, not an uncertainty.

**PITFALLS**
- Return `Verdict`, never `bool`.
- **Never fuzzy-match numbers.** `3` and `4` are similar as strings and different as containers.
- **`token_set_ratio` scores `"ABC Trading"` against `"ABC Trading Sdn Bhd Malaysia Branch"` at
  100** — it ignores extra tokens entirely. Use `ratio` on normalised strings, or `WRatio` with
  a written justification.
- **Do not strip company suffixes.** `ABC Sdn Bhd` and `ABC Pte Ltd` are different legal
  entities.
- **P-ADDRESS — per-field thresholds are mandatory, not optional.** Party fields carry a wrapped
  address continuation:
  ```
  Shipper/Exporter: APRIL FAR EAST (M) SDN BHD
    TOWER 2, AVENUE 5, LEVEL 6; BANGSAR SOUTH CITY, NO. 8 JALAN KERINCHI; 59200 KUALA LUMPUR
  ```
  M09 correctly says the continuation belongs to the field; this module correctly forbids
  `token_set_ratio`. **Together they are a trap**: comparing 120-character address blobs with
  `ratio` puts a re-wrapped address at 0.85–0.95, inside a grey band with a 0.98 threshold, on a
  large fraction of records. Either give address-bearing fields their own looser threshold, or
  compare the **first line (the party name) strictly** and the address separately and advisorily.
  Without this, grey-zone volume dominates the run.
- Epsilon for quantities is explicit, in config, with a reason.

---

### M11 · `state/machine.py` — rewritten in v2

**The only module that may assign `Record.state`.**

```python
def raise_state(rec: Record, new: RecordState, reason: str | None = None) -> None:
    """Monotone. May only move UP the precedence ladder. Never downgrades."""
    cur = rec.state
    if cur is None or STATE_PRECEDENCE[new] > STATE_PRECEDENCE[cur]:
        rec.state, rec.reason = new, reason

def evaluate(rec: Record, cfg: Config) -> Record:
    # 1 — classification must have succeeded
    if rec.category is None:
        raise_state(rec, ESCALATED, "classification_conflict"); return rec

    # 2 — non-comparison records resolve HERE, not inline in the pipeline
    if rec.category != cfg.comparison_category:
        raise_state(rec, RESOLVED); return rec

    # 3 — CARDINALITY IS ASSERTED, NOT QUANTIFIED.   <-- the v1.0 defect
    if set(rec.comparisons) != set(cfg.fields):
        raise_state(rec, ESCALATED, "missing_value"); return rec

    verdicts = {f: c.verdict for f, c in rec.comparisons.items()}
    rec.defects    = [f for f, v in verdicts.items() if v is MISMATCH]
    rec.unresolved = [f for f, v in verdicts.items() if v is CANNOT_DETERMINE]

    # 4 — a CONFIRMED defect outranks an unknown field
    if rec.defects:
        raise_state(rec, RESOLVED); return rec
    if rec.unresolved:
        raise_state(rec, ESCALATED, "missing_value"); return rec
    raise_state(rec, RESOLVED); return rec
```

> **v2 change 1 (fixes C1).** Step 3 asserts set equality against the field registry. `all([])`
> can no longer produce `RESOLVED`, because an empty comparison map fails the cardinality check
> before any quantifier runs.
>
> **v2 change 2 (fixes C1's other half).** `raise_state` is **monotone**. An `ESCALATED` set by a
> raising stage can never be overwritten by a later `RESOLVED`. v1.0's `⟺` and `⟸` were in
> direct logical conflict for exactly this case and gave no precedence.
>
> **v2 change 3 (fixes C7).** `evaluate` returns at each branch and assigns through one function.
> v1.0's suggested `finally: if state is None: state = FAILED` preserved a half-assigned
> `RESOLVED` if the evaluator raised *after* setting it. `run_stage` now sets `FAILED`
> **unconditionally** on the exception path (M13).
>
> **v2 change 4 (fixes C3) — and this one has a real cost.** v1.0 let `CANNOT_DETERMINE`
> dominate `MISMATCH`, so a record with a confirmed consignee mismatch and an unreadable weight
> was reported `NEEDS_REVIEW, has_defect: false` — **a detected defect, thrown away.**
> v2 reverses it.
> **The cost:** the external schema cannot express "mismatch **and** one field unchecked". The
> submission says `MISMATCH` and the unchecked field is invisible to the scorer. This is a
> deliberate trade in favour of not discarding confirmed defects, and `rec.unresolved` is written
> to the review queue as a **separate entry** so a human still sees it. If you disagree, flip the
> two branches in step 4 and record why.

**PITFALLS**
- `state` has **no default**. A default of `RESOLVED` is the single most dangerous line of code
  in this system.
- `evaluate` **requires `cfg`**. v1.0's `evaluate(record) -> Record` could not implement its own
  rule: it needed the field registry to know what "all 7" means and the category string to
  branch on. The three escapes — a hidden global, hardcoding `7`, hardcoding the category — are
  all worse than passing config.
- Nothing outside this module writes `state`.

---

### M12 · `review/queue.py`

```python
def write_queue(records, path) -> None       # each entry carries decision: null
def load_decisions(path) -> dict[tuple[str,str], Decision]   # (email_id, field)
def apply_decisions(rec, decisions) -> Record                # dataclasses.replace
```

**PITFALLS**
- **Decisions are an INPUT, applied at the start of every run.** If they live only in a
  regenerated report, the next run erases them and the reviewer's trust is gone permanently.
- Key by **`(email_id, field)`** — two escalations on different fields of one email overwrite
  each other under a single key.
- **P-HANDOFF — the reviewer will edit the wrong file, and v1.0's layout invited it.** v1.0 wrote
  `review_queue.json` and expected the human to create a separate `resolved.json`. The file the
  reviewer is *handed* is the queue, so the natural action is to annotate it in place — and the
  next run overwrites it. That is the exact trust-loss failure this module exists to prevent,
  arriving through the file layout instead of the logic.
  **Fix:** the queue carries a `"decision": null` field the human fills in, and the **same file**
  is read back. No second artifact.
- `Comparison` is frozen — overriding uses `dataclasses.replace`, which also makes idempotency
  trivially true.
- An entry must be **self-sufficient**: field, both raw values, both `SourceRef`s, the strategy,
  and why it stopped. "Uncertain" alone moves the whole job to the human.

---

### M12b · `llm/`

```python
class CachedLLM(LLMClient):
    def __init__(self, inner, cache, prompt_version: str)
```

**PITFALLS**
- Cache key = `sha256(prompt_version + rendered_prompt)`. Keying on input alone means a prompt
  change silently reuses old answers.
- Temperature 0 **and** a fixed seed where supported. **Temperature 0 is not a determinism
  guarantee** — batching and GPU reduction order vary, and ollama's default seed is not fixed.
  See I6 as revised.
- Cache **successes only**, or a fixed bug never takes effect.
- `complete()` must time out.
- Constrain output with `choices`; validate on return.
- Degraded mode is required (§8).

---

### M13 · `pipeline.py` — new in v2

> v1.0 listed `cli.py` as M13 in the module map and then never specified it. The per-record
> stage sequence, results accumulation, the T1 assertion and `run_summary.json` had **no owning
> module**. Put in `cli.py` they would be untestable without argv.

```python
def run_stage(rec: Record, fn: Callable, name: str, cfg: Config) -> Record:
    """The ONLY broad `except Exception` in the system."""
    try:
        return fn(rec, cfg)
    except ShipdocError as e:
        raise_state(rec, ESCALATED, reason_key(e))
        rec.trace.append(StageEvent(name, "escalated", str(e)))
        return rec
    except Exception as e:                      # noqa: BLE001 — deliberate
        rec.state, rec.reason = FAILED, "unhandled"      # UNCONDITIONAL
        rec.trace.append(StageEvent(name, "failed", traceback.format_exc()))
        return rec

def process(rec: Record, cfg: Config, llm) -> Record:
    rec = run_stage(rec, stage_classify, "classify", cfg)
    if rec.category == cfg.comparison_category and rec.state is not FAILED:
        rec = run_stage(rec, stage_route_by_name, "route", cfg)
        if not _escalated(rec):                          # SHORT-CIRCUIT  <-- v1.0 had none
            rec = run_stage(rec, stage_extract,  "extract",  cfg)
        if not _escalated(rec):
            rec = run_stage(rec, stage_confirm,  "confirm",  cfg)
        if not _escalated(rec):
            rec = run_stage(rec, stage_normalise,"normalise",cfg)
        if not _escalated(rec):
            rec = run_stage(rec, stage_compare,  "compare",  cfg)
    rec = apply_decisions(rec, decisions)
    rec = evaluate(rec, cfg)                             # the ONLY state authority
    assert rec.state is not None, f"T1 violated: {rec.email_id}"
    return rec
```

**PITFALLS**
- **The short-circuit is load-bearing.** v1.0's flow ran every stage unconditionally after a
  raising stage, which is how an escalated record still reached `evaluate` with an empty
  comparison map.
- **No state assignment outside `evaluate` and `run_stage`.** v1.0 assigned
  `state = RESOLVED` **inline** for non-comparison records — bypassing M11 for 394 records, 76%
  of the corpus, on the one function that owns invariant I1.
- The `FAILED` assignment in the generic handler is **unconditional**, not `if state is None`.

---

### M14 · `adapters/`

**The only module containing external vocabulary.**

```python
# reason_map.py — moved here from errors.py in v2
REASON: dict[str, str] = {
    "missing_attachment":     "missing_attachment",
    "wrong_doc_type":         "wrong_doc_type",
    "unhandled":              "unreadable",
    "extraction_failed":      "unreadable",
    "missing_value":          "missing_value",
    "classification_conflict":"missing_value",
}
```

| Internal | `status` | `review_reason` | `defect_fields` | `has_defect` |
|---|---|---|---|---|
| `RESOLVED`, `defects` empty | `OK` | `null` | `[]` | `false` |
| `RESOLVED`, `defects` non-empty | `MISMATCH` | `null` | `rec.defects` | `true` |
| `ESCALATED` | `NEEDS_REVIEW` | `REASON[rec.reason]` | `[]` | `false` |
| `FAILED` | `NEEDS_REVIEW` | `unreadable` | `[]` | `false` |

**Field names (now attested from README, closing v1.0 Open Item 1):**
`shipper`, `consignee`, `notify_party`, `port_of_loading`, `port_of_discharge`,
`container_count`, `gross_weight_kg`.

**PITFALLS**
- **Build the output by iterating the input corpus**, looking up results — not by iterating
  results. A record that died before producing anything must still emit an entry (I7).
- The `NEEDS_REVIEW` row's `has_defect: false` / `defect_fields: []` is supported by all 520
  rows of `sample_submission.json`, which carry exactly that shape.

---

### M15 · `infra/`

**PITFALLS**
- Cache key = `sha256(bytes) + extractor_name + extractor_version`.
- **P-GATE-CACHE — cache the raw extraction, apply the gate outside it.** v1.0 cached
  `ExtractedDoc`, whose `ok` field is the **gate's** verdict — but the gate's inputs are
  *config*, not extractor version. Lower `min_extract_chars` from 120 to 80, re-run, observe no
  change, lose an hour. That is the exact bug class v1.0 warned about, reintroduced through a
  door it did not check. Either cache pre-gate, or add a config hash to the key.
- Structured JSON logs, one object per stage event. Never log full document text.
- Cache writes are atomic — temp file plus rename.

---

## 6. Control flow — single pass

```
load config ──▶ validate types against COMPARATORS ──▶ fail fast
     │
     ▼
load review_queue.json, read filled-in `decision` fields
     │
     ▼
for each email, sorted by email_id:          ◀── records independent, parallelisable
     │
     ├─ classify                    ─▶ category | None
     ├─ if comparison category and not FAILED:
     │     ├─ route_by_name         ─▶ missing_attachment · filename/id mismatch
     │     ├─ [short-circuit if escalated]
     │     ├─ detect + extract ×2   ─▶ unreadable
     │     ├─ [short-circuit]
     │     ├─ confirm_doc_type      ─▶ wrong_doc_type
     │     ├─ [short-circuit]
     │     ├─ normalise ×2          ─▶ sentinels, labels, values, ports, verify
     │     ├─ [short-circuit]
     │     └─ compare_all           ─▶ EXACTLY len(cfg.fields) comparisons
     ├─ apply_decisions
     ├─ evaluate(rec, cfg)          ─▶ the only state authority
     └─ assert rec.state is not None
     │
     ▼
write review_queue.json (decision: null) · submission.json
      report.txt · run_summary.json
```

> **Pass 2 is deleted.** v1.0 §6.2 loaded a "results" artifact that §6.1 never wrote, which
> implied a full `Record` serialisation layer — transitively `ExtractedDoc`, `Block`,
> `SourceRef`, `FieldValue`, `Comparison`, `StageEvent` — that no module owned. The capability
> that matters is decisions-as-input, which is already in the single pass. **To merge a human
> decision, re-run.** The extraction cache makes that cheap, which was pass 2's own argument for
> itself.

---

## 7. Cross-cutting invariants

| # | Invariant | Enforced by |
|---|---|---|
| **I1** | Every record exits with a non-`None` state | M13 assert |
| **I2** | `OK` ⟹ `len(comparisons) == len(cfg.fields)` **and** all `MATCH` | M11 step 3 + M14 |
| **I3** | Every `FieldValue.raw_text` appears in `ExtractedDoc.text` | M09 `verify.py` |
| **I4** | No extractor raises | M06 decorator |
| **I5** | **`status` values, `review_reason` values and submission key names** appear only in `adapters/` | CI grep |
| **I6** | Two runs **from a cleared cache** produce identical output | test, not mechanism |
| **I7** | Every record appears in the submission | M14 iterates the corpus |

> **I5 narrowed in v2.** v1.0 claimed the core was independent of the external schema and
> proposed `grep -rE 'BL_COMPARISON|NEEDS_REVIEW|email_id' src/ --exclude-dir=adapters`.
> **That check is red on day one on at least four files, unavoidably:** `types.py` needs
> `email_id` as the record identity; `state/machine.py` branches on the comparison category;
> `classify/semantic.py` must constrain the model to the five exact strings — the `choices` list
> **is** the external vocabulary; `review/queue.py` keys on `email_id`.
>
> The five categories are simultaneously the domain vocabulary and the external schema. Hiding
> that behind an adapter would require a parallel internal enum renamed 1:1 at the boundary —
> pure ceremony. **A permanently-red CI check is worse than no check**, because it trains the
> team to ignore CI.
>
> v2 keeps the goal and fixes the test. Categories live in `types.Category` as a `StrEnum`.
> `status`, `review_reason` and submission key names are genuinely adapter-owned and worth a
> grep — and that grep is green.
>
> **I6 restated.** v1.0's test ran the pipeline twice and diffed the submission. Run 1 populates
> the LLM cache, so **run 2 is a pure cache-hit run and the test passes by construction** — it
> cannot detect the non-determinism it was written to detect. The test now clears the cache
> between runs, and I6 claims only what is true.

---

## 8. Degraded mode

On `LLMUnavailable` the run continues:
- structural classification still partitions the 126 attachment-carrying emails
- label mapping falls back to the static synonym list
- **the 394 attachment-free records have no category** → `ESCALATED`, reason
  `classification_conflict`
- `run_summary.json` records `degraded: true` and the lost capability

A degraded run that completes and reports honestly is correct. A stack trace is not.

---

## 9. Test plan

| Level | What | Example |
|---|---|---|
| Unit | Each extractor on a crafted file | `.docx` with text only in tables |
| Unit | Each comparator at boundaries | similarity exactly at threshold; both sides `N/A` |
| Property | Extractor contract | random bytes: never raises; `not ok ⟹ text == ""` |
| **Golden** | `email_507`, `email_509` | `NEEDS_REVIEW` / `missing_attachment` — **the v1.0 regression** |
| **Golden** | `email_501`, `503`, `505` | `NEEDS_REVIEW` / **`wrong_doc_type`**, not `unreadable` |
| **Golden** | `email_516` | gross weight is a sentinel ⇒ never `MATCH` against another sentinel |
| **Golden** | `email_511`–`515` | `unreadable` until OCR ships; never `OK` |
| **Property** | Cardinality | for every comparison record: `len(comparisons) == len(cfg.fields)` |
| **Property** | Monotonicity | `raise_state` never lowers precedence — fuzz the order |
| Fault injection | Exception at each stage | `FAILED`, never `OK` |
| Adversarial | corrupt PDF, 0-byte, `.png` named `.txt`, 100 MB, `.zip` | 5 defined outcomes, 0 crashes |
| Determinism | full run twice, **cache cleared between** | byte-identical submission |
| Coupling | I5 grep | empty |

---

## 10. Build sequence — reordered in v2

| # | Build | Why |
|---|---|---|
| **1** | `types`, `errors`, `config`, extractor contract, `terminal.py`, `state/machine.py` | The contract everything plugs into. `evaluate` with its cardinality assertion exists before anything can violate it. |
| **2** | `ingest`, `adapters/submission`, `pipeline.py`, `cli` | 520 placeholder entries on day 1. Baseline score; I7 proven end to end. |
| **3** | `classify/structural` + **`classify/semantic`** + `llm` + cache + `arbiter` | **76% of the corpus and 30% of the score.** Structural alone *cannot* decide the 394 — that is M07's own pitfall. Also de-risks the only non-deterministic dependency first. |
| **4** | `detect`, `extract/text`, `normalise` (incl. `sentinels`), `compare` | **94 complete comparisons** |
| **5** | `extract/pdf` + `route/confirm` | +15 comparisons; confirm catches the 5 planted wrong-doc files |
| **6** | `extract/xlsx`, **then** `extract/docx` | +7, then +8 — **docx alone unlocks zero** |
| **7** | `extract/image` (OCR) **or** corrupt-PDF handling | 5 emails. **Run `pdfimages -list` first** — 511/515 at ~770 bytes are likely malformed, not scanned. |
| **8** | `review/queue` with `decision: null` handoff | Human-in-the-loop closes |

> **v2 change.** v1.0 put semantic classification at stage 5, after all extraction work, and
> sequenced format handlers by file count. Both were wrong: classification carries the largest
> scoring component, and file count does not equal unlocked comparisons.

**Critical path:** extractor contract → placeholder submission → semantic classification →
text extraction → comparison. Everything after is incremental coverage on a system that is
already scoring and already safe.

---

## 11. Open items

| # | Item | Severity | Status |
|---|---|---|---|
| 1 | `defect_fields` spellings | ~~High~~ | **CLOSED** — all seven attested in README |
| 2 | `NEEDS_REVIEW` field values | ~~Medium~~ | **CLOSED** — `sample_submission.json`, all 520 rows |
| 3 | PDFs without a text layer | ~~Medium~~ | **CLOSED** — 8 of 28, verified |
| 4 | `.xlsx` / `.docx` readability | Medium | Open — 30 files, open 3 of each |
| 5 | Full label / unit / count ranges | ~~Medium~~ | **Partly closed** — 64 labels, 38 count forms harvested |
| 6 | Filename anchoring for name variants | Low | Open — decide and document |
| **7** | **Are 511/515 scanned, or malformed?** | **Medium** | **New** — `pdfimages -list` decides OCR vs corrupt-file handling |
| **8** | **Grey-band volume after per-field thresholds** | **Medium** | **New** — measure before tuning; P-ADDRESS predicts it dominates |

---

## Appendix A — `fields.yaml`

```yaml
comparison_category: BL_COMPARISON

sentinels: ['^n/?a$', '^tba$', '^tbd$', '^nil$', '^-+$', '^_+$', '^$']

fields:
  shipper:
    type: text
    required: true
    threshold: 0.98
    grey_low: 0.85
    address_bearing: true        # looser threshold — see M10 P-ADDRESS
    synonyms: ["Shipper/Exporter:", "SHIPPER:", "Shipper:"]

  consignee:
    type: text
    required: true
    threshold: 0.98
    grey_low: 0.85
    address_bearing: true
    synonyms: ["Consignee (Non-Negotiable):", "To the Order of:",
               "CONSIGNEE:", "Consignee:"]

  port_of_loading:
    type: port
    required: true
    synonyms: ["Port of Loading (POL):", "Port of Loading:",
               "Load Port:", "POL:"]

  container_count:
    type: integer
    required: true
    extract: '(\d+)\s*x\s*\d+'
    synonyms: ["No. of Containers or Packages:", "No. of Containers:",
               "Container Count:"]

  gross_weight_kg:
    type: quantity
    unit: kg
    required: true
    conversions: { MT: 1000, T: 1000, LBS: 0.45359237 }
    anti_synonyms: ["NET WEIGHT:", "Net Wt:", "NETT WEIGHT:"]   # see M09 P-NET
    synonyms: ["Gross Weight (KG):", "Gross Wt (kgs):",
               "Gross Weight(KGS):", "GROSS WEIGHT:"]
```

> Synonyms here are seeded from the verified harvest (64 distinct labels). Complete them from
> the full census before stage 4; a label the map does not recognise becomes `missing_value` on
> a field that was present.

---

## Appendix B — What v1.0 got right

Kept unchanged, and worth defending:

- **`CANNOT_DETERMINE` as a first-class third verdict.** Every correctness defect in v1.0 was
  plumbing leaking around this idea, never the idea itself. It is why the design was fixable
  rather than replaceable.
- **The never-raises extractor contract with a terminal tier**, built before any handler.
- **`SourceRef` on every value** — the review queue is worthless without it.
- **Decisions as an input, keyed `(email_id, field)`.**
- **`read_bytes()` never `read_text()`** — the loader decodes with `errors="replace"`, so the
  failure would have been silent mojibake.
- **The docx-tables pitfall and the xlsx trio** — all four are the actual first bugs in those
  handlers.
- **"Harvest synonyms from observed labels, not from imagination"** — vindicated by
  `To the Order of` ×37, which nobody would have guessed.
- **Longest-label-first** — attested, though M09 P-NET shows where it points the wrong way.
- **"Do not strip company suffixes"** and the **`token_set_ratio` warning.**
- **"A reason code exists because a case exists"** — five planted wrong-document files.
- **Extractor version in the cache key, prompt hash in the LLM cache key.**

---

## Appendix C — Review disposition

**31 findings. 29 accepted, 2 accepted with a qualification. 0 rejected.**

| ID | Finding | Disposition |
|---|---|---|
| C1 | `all([])` ⇒ `RESOLVED`; `email_507` reports `OK` | **Accepted — fatal.** M11 rewritten: cardinality assertion + monotone states |
| C2 | Partial field map ⇒ partial comparison map ⇒ `OK` | **Accepted.** M10 `compare_all` iterates the registry |
| C3 | `CANNOT_DETERMINE` discards a confirmed `MISMATCH` | **Accepted with cost stated.** M11 step 4; schema cannot express both, so `unresolved` goes to the queue |
| C4 | Quality gate turns `wrong_doc_type` into `unreadable` | **Accepted.** Label check moved to `route/confirm.py` |
| C5 | `None` guard misses `N/A`, `_______`, `TBA` | **Accepted.** New `sentinels.py`; identity short-circuit forbidden |
| C6 | Inline state assignment bypasses M11 for 76% | **Accepted.** All state via `evaluate`; M07 returns `str \| None` |
| C7 | `finally: if state is None` preserves half-assigned `RESOLVED` | **Accepted.** Unconditional `FAILED` in `run_stage` |
| C8 | Filename number not bound to `email_id` | **Accepted.** One-line assertion |
| B1 | M08 signature contradicts §6.1 ordering | **Accepted.** Split into `by_name` + `confirm` |
| B2 | `tuple[str, float]` cannot express escalation | **Accepted** (with C6) |
| B3 | `evaluate` cannot implement its own rule | **Accepted.** Takes `cfg` |
| B4 | `SIGALRM` absent on Windows; threads cannot interrupt C extensions | **Accepted.** `ProcessPoolExecutor` + picklability stated as a contract consequence |
| B5 | Pass 2 loads an artifact nothing writes | **Accepted.** Pass 2 deleted |
| B6 | No orchestrator module | **Accepted.** M13 `pipeline.py` added |
| B7 | `type` and `strategy` used interchangeably | **Accepted.** `strategy` deleted |
| B8 | T3 unenforceable for reconstructed formats | **Accepted.** T3 verifies extraction fidelity |
| B9 | Frozen `Comparison` needs `replace` | **Accepted** |
| K1–K3 | I5 red on day 1; schema coupling is structural | **Accepted.** I5 narrowed; `reason_map` moved to `adapters/` |
| K4 | Quality gate makes `extract/` depend on domain labels | **Accepted** (with C4) |
| P1 | Missing values are non-empty strings | **Accepted** (= C5) |
| P2 | `NET WEIGHT` vs `GROSS WEIGHT`; longest-match points the wrong way | **Accepted.** `anti_synonyms` added |
| P3 | CJK in a required label | **Accepted.** Strip-before-lookup; §1.2 note added |
| P4 | Sequence by unlocked comparisons, not file count | **Accepted.** Stage 6 reordered |
| P5 | 8 of 28 PDFs have no text layer | **Accepted.** §1.3 corrected; OCR to stage 7; new Open Item 7 |
| P6 | SI is authoritative, so presence is asymmetric | **Accepted.** `si present, bl absent ⇒ MISMATCH` |
| P7 | Address continuation floods the grey zone | **Accepted.** Per-field thresholds mandatory; new Open Item 8 |
| P8 | "decide + log" undefined | **Accepted.** Grey ⇒ `CANNOT_DETERMINE` |
| P9 | Gate cached inside `ok` | **Accepted.** Cache pre-gate |
| P10 | Reviewer edits the wrong file | **Accepted.** `decision: null` in the queue itself |
| P11 | Filename role collision drops a document | **Accepted.** Assertion added |
| P12 | Multi-size container has no integer representation | **Accepted.** `+` or two size tokens ⇒ `CANNOT_DETERMINE` |
| P13 | I6 test unfalsifiable; temp 0 ≠ determinism | **Accepted.** Cleared-cache test; I6 restated |
| P14 | 76% never touches the comparison engine | **Accepted.** Drives the stage-3 reorder |
| P15 | Open items 1–2 answerable from README | **Accepted.** Both closed |
| §6 | Delete comparator registry; delete two confidence floats; delete pass 2 | **Accepted, all three.** `Block.confidence` kept for OCR |
| §7 | Move semantic classification to stage 3 | **Accepted** |

**Qualifications on two otherwise-accepted findings**

- **C3.** The fix is right for scoring, and it is not free. The external schema has no way to say
  "mismatch **and** one field unchecked", so the scorer sees `MISMATCH` and the unchecked field
  is invisible to it. v2 takes the trade because discarding a *detected* defect is worse, and
  routes `unresolved` to the human queue so the information is not lost to the people who act on
  it. It is recorded here as a costed decision, not a free win.
- **K1.** `types.py` carrying `email_id` is not really "external schema leakage" — it is the
  record's identity. The finding still stands, because it demonstrates the **grep was a bad
  test**, which is the point that matters. A test that fires on benign code is one the team
  disables.

---

*End of specification v2.0.*
