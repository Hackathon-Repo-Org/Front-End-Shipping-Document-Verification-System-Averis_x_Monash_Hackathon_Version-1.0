# Testing and inspecting shipdoc

You do not need to understand the system to test it. Six levels, each standing alone.
Start at Level 0 and stop wherever you have what you need.

Everything here assumes Tier 1 of `SETUP.md` is done and your venv is active.

> **A note on how these checks are written — please keep it this way.**
> No verification step redirects output to `/dev/null`, every step checks its exit
> code, and any step that compares an output file first asserts the file was
> *rewritten by that run*. This is not pedantry: Phase 5 concluded it had changed
> nothing because the submission hash was unchanged — on a file that had never been
> written, because the command had been failing silently for hours.

---

## Level 0 — "Is it alive?"

One command, about 40 seconds.

```powershell
python -m shipdoc doctor
```

**Expected:** a list of `[ok  ]` lines ending in

```
  RESULT: PASS — shipdoc is ready
```

Add `--fast` to skip the test-suite check (about 5 seconds instead).

**What a difference means:**

| You see | Meaning |
|---|---|
| `[FAIL] corpus  0 emails` | wrong working directory — `cd` to the repo root |
| `[FAIL] package imports` | `pip install -e ".[dev]"` was not run, or venv not active |
| `[--  ] OCR` / `[--  ] LLM` | **normal on a fresh machine.** Optional. The system runs without them |
| `RESULT: FAIL` | exit code is 1; something required is broken. The `->` line under each failure says what to do |

---

## Level 1 — "Do the tests pass?"

```powershell
python -m pytest -q
```

**Expected:** `642 passed` in about 50 seconds. Zero failures is the thing that
matters; the count rises as tests are added.

| Directory | What it covers |
|---|---|
| `tests/unit/` | one module at a time — classification, extraction, sentinels, label matching, port resolution, the review queue |
| `tests/property/` | contracts and invariants that must hold for *every* input: the extractor never raises, state transitions are monotone, the layering rule, and that the answer key cannot leak into the pipeline |
| `tests/integration/` | the whole corpus end to end — 520 records, submission schema, CLI behaviour |
| `tests/golden/` | the 20 planted edge cases, each asserted by name — all 20 pass |

Run one group: `python -m pytest tests/property -q`

---

## Level 2 — "Run it on everything"

```powershell
python -m shipdoc
```

**Expected:** about 3 seconds with a warm cache (20–60 seconds cold, or ~6 seconds
with `--no-llm`), then a JSON summary ending `"records_total": 520`. Exit code 0.

Four files land in `output\`:

| File | What it is |
|---|---|
| `submission.json` | 520 entries in the organisers' schema — the deliverable |
| `run_summary.json` | counts by state and by internal reason, plus `degraded` |
| `report.txt` | human-readable discrepancy report, SI and BL side by side |
| `review_queue.json` | every escalation with full evidence and a `decision` field |

**Check the run actually wrote something** (Amendment 1 — do this, don't assume):

```powershell
Remove-Item output\submission.json -ErrorAction SilentlyContinue
python -m shipdoc
if ($LASTEXITCODE -ne 0) { "FAILED: exit $LASTEXITCODE" }
Test-Path output\submission.json      # must print True
```

**The review queue is read back on the next run.** Open `output\review_queue.json`,
set a `"decision"` to `"match"`, `"mismatch"` or `"cannot_determine"`, re-run, and
your answer is applied and preserved. There is no second file to maintain.

---

## Level 3 — "Look at one email"

The most useful command in the repo. Shows the seven fields side by side with the
evidence for each.

```powershell
python -m shipdoc inspect email_013
```

**Expected** — a genuine planted defect:

```
email_013    category=BL_COMPARISON    state=resolved

  field              verdict    SI (authoritative)             BL
  port_of_discharge  DEFECT     MOMBASA, KENYA (KEMBA)         TUTICORIN, INDIA (KEMBA)
                                'MOMBASA' vs 'TUTICORIN', similarity 0.125
                                evidence: SI attachments/email_013_SI.txt:line 10 | BL ...:line 10

  CONFIRMED DEFECTS : port_of_discharge
```

Note both documents carry the same stale code `(KEMBA)` while the place names differ —
that is how this corpus plants port defects, and it is why UN/LOCODE resolution is
currently switched off (see the last section).

### Records worth looking at

| Command | What you should see |
|---|---|
| `python -m shipdoc inspect email_501` | `wrong_doc_type` — the BL attachment is a **COMMERCIAL INVOICE**. No comparison performed, and the trace says why |
| `python -m shipdoc inspect email_503` | `wrong_doc_type` — a **CERTIFICATE OF ORIGIN**. It carries a shipper and a consignee, so a label count alone would let it through |
| `python -m shipdoc inspect email_507` | `missing_attachment` — only an SI, no BL. Zero comparisons; nothing is compared against nothing |
| `python -m shipdoc inspect email_511` | `unreadable` — a malformed PDF. `pdfimages` finds no images, so OCR cannot help and this is the correct answer |
| `python -m shipdoc inspect email_512` | a **scanned** PDF. With Tier 2 (OCR) it is read; without it, `unreadable` |
| `python -m shipdoc inspect email_516` | the placeholder group — the SI says `Gross Weight毛重(KGS): N/A` and `NET WEIGHT: _______ MTS`. The sentinel must never compare equal to another sentinel |

Add `--no-llm` to any of these to skip the model.

**What a difference means:** if a field shows `unknown` where you expected `match`,
read the `detail` line under it — it names the threshold or the reason.

---

## Level 3b — "Does it hold up on emails it has never seen?"

The 520-email corpus is the only data the system was built against, so every number
on this page is a fact about *that corpus*. `tests/fixtures/adversarial/` holds three
hand-written emails that attack the seams it does not test. They are **synthetic and
ours** — not from the organisers, and with no official answer key.

```powershell
python -m shipdoc --source tests\fixtures\adversarial --out output_adversarial
python -m shipdoc inspect email_997 --source tests\fixtures\adversarial
```

They also run as assertions in the normal suite:

```powershell
python -m pytest tests/integration/test_adversarial.py -q
```

**Expected:** `19 passed, 1 xfailed`. The xfail is deliberate and `strict` — it is the
bare-UN/LOCODE case, which only passes if someone flips the port-resolution flag, and
strict mode makes that flip fail the suite so the decision document gets read first.

What they caught, and what each one now shows on screen:

| Email | The trap | Result |
|---|---|---|
| 997 | `NOTIFY PARTY: SAME AS CONSIGNEE` | resolves against that document's own consignee; `inspect` prints *"SI said 'SAME AS CONSIGNEE' — value taken from this document's consignee"* |
| 997 | `22,450.50` vs `22.450,50` | same quantity, European separators |
| 997 | POL and POD **swapped** | both caught — the genuine defect |
| 998 | subject says INVOICE, body says audit the BL | body wins |
| 999 | BL label reads bare `Containers:` | extracted; previously a false defect against an identical value |
| 999 | BL `NET WEIGHT` = SI's `GROSS WEIGHT` | refused — the anti-synonym list holds |

`inspect` now also distinguishes the two ways a field can be blank, which is the
difference a reviewer needs and could not previously see:

```
  gross_weight_kg    unknown    45,120.00 KGS                  —
                                no gross_weight_kg label found in the BL —
                                extraction miss, not a confirmed omission
                                BL: no label matching gross_weight_kg was found
```

"We could not find the label" is a fact about our synonym list; "the carrier left it
blank" is a fact about the document. Only the second is a defect.

---

## Level 4 — "Is it correct?"

Requires the organiser bundle at `..\sdoc-server\` (SETUP.md Tier 3b).

```powershell
python -m shipdoc
python eval\evaluate.py
```

**Expected:** the four scoring axes, computed by importing the organisers' own
`scoring.py` — not a reimplementation — plus every disagreement grouped by type, a
table for the 20 planted edge cases, and four named questions. It also writes
`eval\report.txt` so the numbers survive the terminal.

As of this handoff:

```
  stage1 macro-F1     0.9526   (weight 0.30)
  stage3 defect-F1    0.9890   (weight 0.20)   precision 1.000
  end-to-end          0.9348   (weight 0.50)   43/46
  reliability         esc-P 0.408 esc-R 1.000  (weight 0.00)
  FINAL SCORE         0.9510
```

**The evaluator is a measuring instrument, never an input.** No module under
`src/shipdoc/` may read the answer key, import the evaluator, or mention a specific
`email_id`. `tests/property/test_no_answer_key_leak.py` enforces both halves and has
been shown to fail when either is violated.

---

## Level 5 — "Try to break it"

Deliberate abuse. The contract is: **terminate, escalate, never crash.**

```powershell
python -m pytest tests/property/test_extractor_contract.py -q
```

**Expected:** all pass. That file fuzzes the terminal extractor with random bytes
(40 seeded cases), 10 MB of zeros, a PNG header followed by garbage, and truncated
files of several formats.

Verified by hand, each returning a failed result rather than raising:

| Input | Result |
|---|---|
| empty file | `ok=False`, `EmptyFileError` captured |
| corrupt PDF (`%PDF-1.4 truncated garbage`) | `ok=False`, `FileDataError` captured |
| `.png` renamed `.txt` | `ok=False`, `below_min_extract_chars` |
| 10 MB of zeros | `ok=False`, parser error captured |
| a bare ZIP that is not a `.docx` | `ok=False`, `no_handler_for_mime` |

Two rules make this hold: every `extract()` is wrapped in a decorator that converts
any `Exception` into a failed result, and `ok=True` with empty text is corrected to a
failure. `BaseException` (Ctrl-C) still propagates — we convert errors, not signals.

---

## What this system does NOT do yet

Read this before you go looking. Finding a gap yourself costs trust; being told first
does not.

**Not built**
- **No UI.** `inspect` is the view a web UI would wrap in HTML. No API, no server.
- **No database.** Everything is files on disk.
- **Cloud is not wired.** Local only.
- **`tests/golden/` is an empty directory.** The golden cases exist and pass — they
  are inside `tests/unit/test_stage4_compare.py`. Moving them is cosmetic and was
  deliberately deferred; splitting test files is the one operation that can silently
  lose a test.

**Built but switched off**
- **UN/LOCODE port resolution.** Complete, tested, with the 116k-row table shipped —
  and `flags.port_resolution_enabled: false`. Measured, it destroys **15 genuine
  defect detections** to gain 14, because this corpus plants port defects as a
  name/code contradiction and the resolver lets a stale code override a differing
  name. The fix direction is written up in
  `docs/decisions/port-resolution.md` under "Fix direction (not implemented)".
  Do not flip the flag without implementing both rules there and re-running
  `tools/bucket_analysis.py`.

**Known bugs, found and not fixed**
- **`SINGAPORE` is eaten as a country token.** `_strip_countries` removes it, so
  `port_of_loading: SINGAPORE (SGSIN)` resolves to an empty identity and reports
  `unknown` on both sides. Singapore is both a country and a port. Visible in
  `python -m shipdoc inspect email_013`. Affects several records.
- **Projection row 2 over-reports.** Appending `suspected` to confirmed defects turns
  an exactly-correct defect set into a wrong one on **6 records** (`email_097`,
  `107`, `291`, `302`, `354`, `435`). Each is a lost end-to-end point for no gain.
- **We escalate 93 records the answer key marks OK** — 80 `missing_attachment`,
  13 `missing_value`. The reliability axis carries zero weight, so this is pure cost
  on the scored axes. It is a deliberate design stance, not an accident: see
  `docs/reports/` for the reasoning.
- **9 false defects** against 44 genuine ones on the records we report `MISMATCH`.
- **12 of 20 planted edge cases exactly right.** The 8 misses are the scan group and
  the placeholder group reporting `MISMATCH` where gold says `NEEDS_REVIEW`.

None of these are being fixed today — they are tomorrow's decisions and the team
takes them together.

---

## Level 6 — "Teach it a label"

The system notices label-shaped lines it does not recognise and asks the model one
closed question about each. **Nothing it suggests takes effect until you approve it.**

```powershell
python -m shipdoc labels list                      # what is pending, with evidence
python -m shipdoc labels approve "Containers:"     # becomes a rule from the next run
python -m shipdoc labels reject  "Vessel:"         # never asked again
```

Approvals land in `config/learned_labels.yaml` with full provenance — who, when,
which model, which prompt version. It is loaded *alongside* `fields.yaml` and never
merged into it, so **deleting that one file reverts every learned rule at once.**

**Which vocabulary produced a run** is recorded in `output/run_summary.json`:

```json
"learned_labels_sha256": "554f11cc…",
"learned_labels_count": 4
```

That field exists because "two runs produce identical output" is only meaningful
against a stated vocabulary. A run that does not say which one it used has quietly
stopped being reproducible.

**What can never be learned** is that two *values* mean the same thing. That is a
judgement about whether two documents agree, and as a permanent rule it would make
the system blind to a genuine change of that party on every future shipment. The
loader refuses such an entry outright:

```powershell
python -m pytest tests/unit/test_learned_labels.py -q    # 21 passed
```
