# DOCKER BUNDLE ANALYSIS

Read-only static inspection. Docker was not started. The answer key and the data
generator were located but **not opened** — see §8.

---

## 1. Inventory

```
sdoc-hackathon-docker/
├── README.md                 1,276   organiser run instructions
├── docker-compose.yml        1,077
├── server/
│   ├── Dockerfile              778
│   ├── README.md             3,830   delivery kit — submission format + scoring model
│   ├── app.py                5,449   FastAPI server
│   ├── loader.py             4,048   byte-identical to ours
│   ├── make_bundle.py        4,834   builds the participant ZIP (strips ground truth)
│   ├── make_docker_bundle.py 3,781   builds this organiser ZIP
│   ├── requirements.txt         49   fastapi, uvicorn[standard]
│   ├── score_cli.py          3,526   offline scorer / leaderboard printer
│   └── scoring.py            7,863   ** the scoring implementation **
└── data_v2/
    ├── README.md             7,079   organiser dataset doc — NOT OPENED (§8)
    ├── ground_truth.json    79,980   ** ANSWER KEY — NOT OPENED **
    ├── sample_submission.json 75,402 identical to ours
    ├── generate.py          13,031   ┐
    ├── emails.py            11,688   │
    ├── pools.py             11,910   ├ data generator — NOT OPENED (§8)
    ├── render.py             8,496   │
    ├── edgecases.py          7,165   │
    ├── shipment.py           5,139   ┘
    ├── inbox/                        520 files
    └── attachments/                  250 files
```

**Extension census:** 522 `.json` (520 inbox + sample_submission + ground_truth) ·
193 `.txt` (192 attachments + requirements.txt) · 28 `.pdf` · 22 `.xlsx` · 12 `.py` ·
8 `.docx` · 3 `.md` · 1 `.yml` · 1 `Dockerfile`.

The two count deltas against our repo (522 vs 521 json, 193 vs 192 txt) are entirely
accounted for by `ground_truth.json` and `requirements.txt`. No data file differs.

---

## 2. Python files — what each does

### Read (scoring/serving logic — the point of this task)

| Path | Size | What it does | Public names | Imports |
|---|---|---|---|---|
| `server/scoring.py` | 7,863 | The scoring implementation, shared by the CLI and the server. Computes four axes and the weighted final score. | `CATEGORIES`, `REVIEW_REASONS`, `DEFAULT_WEIGHTS`, `prf`, `score_stage1`, `score_stage3`, `score_reliability`, `score_end_to_end`, `score_all` | stdlib only (`collections.defaultdict`) |
| `server/app.py` | 5,449 | FastAPI app serving the inbox and scoring submissions. Ground truth is read server-side from a private mount and never returned. | `app`, `health`, `index`, `list_emails`, `get_email`, `get_attachment`, `sample_submission`, `submit`, `ground_truth` | third-party `fastapi`; stdlib `json`, `os`, `pathlib`, `typing`; local `scoring` |
| `server/score_cli.py` | 3,526 | Judges' offline scorer. Loads a ground-truth JSON and a submission, prints a formatted leaderboard or `--json`. | `bar`, `main` | stdlib `argparse`, `json`, `pathlib`; local `scoring` |
| `server/loader.py` | 4,048 | The participant loader. **Byte-identical to our copy.** | `Inbox` | stdlib `json`, `os`, `urllib.request`, `pathlib` |
| `server/make_bundle.py` | 4,834 | Builds the participant ZIP: copies inbox + attachments + sample_submission **without** `ground_truth.json`, then asserts none leaked (`rglob("ground_truth*")`). | `main` | stdlib `argparse`, `shutil`, `pathlib` |
| `server/make_docker_bundle.py` | 3,781 | Builds this organiser ZIP (data + server + compose). | `main` | stdlib `argparse`, `shutil`, `pathlib` |

### Not read — treated as answers under HARD RULE 3

`data_v2/generate.py`, `emails.py`, `pools.py`, `render.py`, `edgecases.py`,
`shipment.py`. These are the generator that produced both the corpus *and* the ground
truth. `edgecases.py` in particular encodes the planted defects by construction, so
reading it is equivalent to reading the answer key. Sizes are in §1; contents unopened.

---

## 3. THE SCORING FORMULA

### The headline

```
final_score = 0.30 × stage1.macro_f1
            + 0.20 × stage3.defect_f1
            + 0.50 × end_to_end.rate
```

`DEFAULT_WEIGHTS = {"stage1": 0.30, "stage3": 0.20, "end_to_end": 0.50}`
(`scoring.py:28`, applied at `scoring.py:175-177`). This confirms the README's
`50% / 30% / 20%` exactly. Weights are overridable via `score_cli.py --weights`, but
the server uses the defaults.

### Axis 1 — `score_stage1` (weight 0.30)

**Macro-F1 over the five categories**, unweighted mean of per-class F1:

```python
macro_f1 = sum(prf(**per[c])[2] for c in CATEGORIES) / len(CATEGORIES)
```

- `accuracy` is also computed and returned but **is not weighted** — only `macro_f1`
  enters `final_score`.
- Macro (not micro) means **each of the five categories counts equally regardless of
  support**. A rare category is worth as much as `GENERAL`.
- A missing `email_id` defaults to `"GENERAL"` (`scoring.py:46`), not to an error.
- `decided_by` is read if present (`scoring.py:55-59`) to report a diagnostic
  `rule_pct` — "how much did you resolve with rules rather than the model". Not scored.

### Axis 2 — `score_stage3` (weight 0.20)

Email-level defect detection F1, over a **restricted population**:

```python
if t["category"] != "BL_COMPARISON":      continue   # gold category
if t.get("status") == "NEEDS_REVIEW":     continue   # gold status
```

- Population is gold-BL_COMPARISON records that were genuinely comparable.
- `pred_defect = bool(s.get("has_defect")) and routed`, where
  `routed = s.get("category") == "BL_COMPARISON"`.
- Also returns `field_f1`, `exact_match_rate`, `defect_precision`, `defect_recall` —
  all diagnostic; only `defect_f1` is weighted.

### Axis 3 — `score_end_to_end` (weight 0.50 — the headline)

```python
if not (t["category"] == "BL_COMPARISON" and t.get("has_defect")): continue
total += 1
routed    = s.get("category") == "BL_COMPARISON"
flagged   = bool(s.get("has_defect"))
fields_ok = set(s.get("defect_fields", [])) == set(t["defect_fields"])
if routed and flagged and fields_ok: success += 1
rate = success / total
```

Population is **only records that gold says carry a defect**. All three conditions must
hold, and `fields_ok` is **exact set equality** — a superset or a subset both score zero.

### Axis 4 — `score_reliability` (weight **0.00**)

Escalation precision / recall / F1 over gold `NEEDS_REVIEW` records, plus a per-reason
breakdown. Computed, returned, printed by the CLI — and **absent from the `final_score`
expression**. It is explicitly diagnostic (`scoring.py:107-115`).

### Is there a penalty for false positives?

**Partially — and this refutes the assumption on half the weight.**

| Axis | Weight | FP penalised? | Mechanism |
|---|---|---|---|
| stage1 macro-F1 | 0.30 | **Yes** | `per[pred]["fp"] += 1` (`scoring.py:54`) lowers that class's precision |
| stage3 defect-F1 | 0.20 | **Yes** | `not gold_defect and pred_defect → fp += 1` (`scoring.py:91-92`) lowers `defect_precision` |
| end-to-end | **0.50** | **No** | Pure recall: `success / total` over gold-defective records only. A defect invented on a clean record is **invisible** to this axis |
| reliability | 0.00 | Yes, but unweighted | `escalation_precision` exists and scores nothing |

So: false positives cost you on **50% of the weight** and are **free on the other 50%**.
Our design assumed a uniform FP penalty; that is true for stage1 and stage3 and false
for the headline metric.

### What `/submit` returns

`scoring.score_all(...)` serialised as JSON:

```
{
  "stage1":      {accuracy, macro_f1, rule_pct, per{cat:{tp,fp,fn}}, confusion{actual:{pred:n}}},
  "stage3":      {defect_precision, defect_recall, defect_f1, field_f1, exact_match_rate, doc_total},
  "reliability": {escalation_recall, escalation_precision, escalation_f1,
                  gold_review, pred_review, per_reason{reason:{total,caught}}},
  "end_to_end":  {success, total, rate},
  "weights":     {stage1, stage3, end_to_end},
  "final_score": float,
  "n_emails":    int
}
```

The **confusion matrix and per-category tp/fp/fn come back on every submission.** That
is a full diagnostic feedback loop, not just a number.

---

## 4. HTTP endpoints and submission validation

| Method | Path | Request | Response |
|---|---|---|---|
| GET | `/health` | — | `{status, emails, scoring_available}` |
| GET | `/` | — | API index |
| GET | `/emails` | — | list of all 520 records, sorted by id, no labels |
| GET | `/emails/{email_id}` | — | one record; 404 if absent |
| GET | `/attachments/{path}` | — | `FileResponse`; path-traversal guarded; 404 if absent |
| GET | `/sample_submission` | — | the sample submission JSON |
| POST | `/submit` | JSON object keyed by email_id | the full scoreboard above |
| GET | `/ground_truth` | `X-Judge-Token` header | **404 unless `REVEAL_GT=1`**; disabled in the shipped compose file |

Served on **`http://localhost:8080`** (compose maps host 8080 → container 8000).

### Rate limiting / caps

**None.** No rate limit, no submission cap, no throttling, no authentication on any
participant endpoint, `restart: unless-stopped`. Submissions can be made as often as we
like — the scoreboard is usable as a development feedback loop, not a one-shot.

### Validation performed before scoring

Minimal. The entire validation surface is:

```python
try:    sub = await request.json()
except Exception:
    raise HTTPException(400, "body must be JSON: {email_id: {category,status,has_defect,defect_fields}}")
if not isinstance(sub, dict):
    raise HTTPException(400, "submission must be a JSON object keyed by email_id")
```

That is all. Specifically the server does **not**:
- require every `email_id` to be present (missing → `GENERAL` / `{}` defaults),
- validate `category`, `status` or `review_reason` against permitted values,
- reject unknown keys,
- check `has_defect` against `defect_fields` for consistency,
- check `defect_fields` names against the seven real fields.

An invalid value simply fails to match gold and scores zero. **The strict schema
validation we built for our stage-2 gate is ours alone — the server will not catch a
malformed submission, it will just quietly score it badly.** That makes our local
validator more valuable, not less.

One documented constraint worth honouring, from `scoring.py`'s own docstring:
`has_defect : bool (true iff status == MISMATCH)`. Our adapter already satisfies this.

---

## 5. `loader.py` — same or changed

**IDENTICAL.** Byte-for-byte:

```
4b71666adcbbc05b4e77e0d498db3a8b  loader.py
4b71666adcbbc05b4e77e0d498db3a8b  sdoc-hackathon-docker/server/loader.py
```

Public API unchanged: `Inbox.emails()`, `get()`, `read_bytes()`, `read_text()`,
`submit()`, `sample_submission()`. **No change required to our M04 adapter.** Pointing
at the server is the one config line we planned: `LoaderInbox("http://localhost:8080")`.

---

## 6. Data consistency verdict

### **IDENTICAL**

| Comparison | Result |
|---|---|
| `diff -rq inbox data_v2/inbox` | no differences — 520 files, identical content |
| `diff -rq attachments data_v2/attachments` | no differences — 250 files, identical content |
| `diff sample_submission.json data_v2/sample_submission.json` | identical |
| email_id sets (`comm -3`) | no id on one side only |
| attachment sets (`comm -3`) | no attachment on one side only |

Every corpus fact our spec and survey rest on is confirmed against the organiser's own
copy. No re-survey needed.

### On `README.md`

`README.md` (repo) and `data_v2/README.md` differ, but **they are different documents,
not two versions of one.** The repo's participant README (2,295 bytes) is not shipped in
the Docker bundle at all; `data_v2/README.md` (7,079 bytes) is the organiser's dataset
documentation, with sections including "Ground-truth schema", "Edge cases", "Categories
& mix" and "Defects". It is answer-bearing and was not opened (§8).

**Our attested strings are independently corroborated by `scoring.py`**, which I read
legitimately:

| Our constant | `scoring.py` | Match |
|---|---|---|
| `types.Category` (5 values) | `CATEGORIES = ["BL_COMPARISON","SI_REQUEST","INVOICE_QUERY","GENERAL","SPAM"]` | exact |
| `REVIEW_REASON` values (4) | `REVIEW_REASONS = ["wrong_doc_type","missing_attachment","unreadable","missing_value"]` | exact |
| status values (3) | docstring: `OK \| MISMATCH \| NEEDS_REVIEW` | exact |

The seven `defect_fields` names do not appear in `scoring.py`, so they remain attested
from the repo `README.md` — which is unchanged, and which our
`test_registry_field_names_match_the_readme` already guards.

---

## 7. Nesting risks and recommended layout

### Current state — no active breakage

| Check | Result |
|---|---|
| `__pycache__` inside the bundle | none |
| `.pytest_cache` inside the bundle | none |
| pytest collection from the bundle | **0 items** (171 collected, all from `tests/`) |
| `loader.py` copies on path | 2, but no shadowing — see below |
| `src/` or `tests/` globbing into the bundle | none; `conftest.py` anchors to `ROOT / "inbox"` |

**No import shadowing today.** `ingest/loader_port.py` loads the provided loader by
explicit file path under the module name `_shipdoc_provided_loader`, never by bare
`import loader`, so a second `loader.py` on disk cannot be picked up by accident. The two
files are byte-identical anyway, so even a mistake would be benign right now.

### The real risks

1. **`ground_truth.json` is now inside our repo tree.** This is the serious one. A
   `.gitignore` stops a commit; it does not stop a recursive glob, a grep, an editor
   search, or an assistant reading files. Every number we produce depends on nobody ever
   reading that file, and it currently sits four directories from our source.
2. **The corpus exists twice.** Any future `ROOT.rglob("email_*.json")` silently returns
   1,040 records instead of 520. Nothing does that today; the pattern is natural enough
   that something will.
3. **Collection is clean by luck.** The bundle contains no `test_*.py`. If a future
   organiser drop adds one, pytest collects it with no warning.

### Recommendation — move it to a **sibling directory outside the repo**

```
Desktop/
├── sdoc-hackathon-bundle/       our repo (unchanged)
└── sdoc-hackathon-docker/       the organiser bundle, moved here
```

Reasons, in order:

- It removes the ground-truth contamination hazard **structurally** rather than by
  policy. Exclusion lists are a promise; a directory boundary is a fact.
- **Nothing breaks.** `docker-compose.yml` mounts `./data_v2` and `build: ./server`,
  both relative to the compose file, so the whole folder relocates intact.
- **We need exactly one thing from it: the URL** (`http://localhost:8080`). There is no
  code dependency, no path dependency, and `loader.py` is identical so no file to copy.

If it must stay inside the repo, the weaker mitigation is all three of: `norecursedirs`
/ `--ignore=sdoc-hackathon-docker` in pytest config, `sdoc-hackathon-docker/` in
`.gitignore`, and an exclusion in any packaging config. I would still move it — the
contamination risk is the kind that is silent until the results are already worthless.

**Not moved.** Awaiting instruction, per the read-only rule.

---

## 8. Answer-key files found (paths only, NOT opened)

| Path | Size | Why not opened |
|---|---|---|
| `sdoc-hackathon-docker/data_v2/ground_truth.json` | 79,980 | The answer key. Labels for all 520 records. |
| `sdoc-hackathon-docker/data_v2/edgecases.py` | 7,165 | Generates the planted edge cases — the answers, in code |
| `sdoc-hackathon-docker/data_v2/generate.py` | 13,031 | Top-level generator; produces the corpus and the ground truth together |
| `sdoc-hackathon-docker/data_v2/emails.py` | 11,688 | Generates emails per category — reveals gold categories |
| `sdoc-hackathon-docker/data_v2/pools.py` | 11,910 | Value pools the documents are built from |
| `sdoc-hackathon-docker/data_v2/render.py` | 8,496 | Renders records to txt/pdf/xlsx/docx |
| `sdoc-hackathon-docker/data_v2/shipment.py` | 5,139 | The shipment data model the defects are applied to |
| `sdoc-hackathon-docker/data_v2/README.md` | 7,079 | Organiser dataset doc. Section **headers** were listed to classify it; the body was not read. Headers include "Ground-truth schema", "Edge cases", "Defects" |

The organiser's own `README.md` confirms the classification: *"⚠️ This package includes
the answer key. Do NOT hand it to participants."* And `make_bundle.py` exists precisely
to strip `ground_truth.json` when building the participant ZIP, asserting
`rglob("ground_truth*")` comes back empty.

For the record: I derived `email_501`–`email_520` as the planted edge-case block from the
**data itself** during the original survey, before this bundle existed. Nothing in this
analysis depends on the generator or the key.

---

## 9. What this changes for our build

Ordered by how much it should change what we do.

### 9.1 Classification gates 100% of the score, not 30%

Both weighted comparison axes require the **predicted** category to be
`BL_COMPARISON`:

```python
routed = s.get("category") == "BL_COMPARISON"    # stage3:81 and end_to_end:157
```

Misclassify one comparison email and you lose it on the 30% axis *and* the 20% axis
*and* the 50% axis. Stage 3 of our build sequence was already reordered to put
classification first; this is the hard confirmation that the reorder was right, and it
raises the stakes. `BL_COMPARISON` **recall** is the single most valuable quantity in the
system — a comparison email misfiled as `GENERAL` is worth strictly more damage than a
`GENERAL` misfiled as `BL_COMPARISON`.

### 9.2 The reliability axis is worth zero, and that cuts against our design

Our architecture escalates when uncertain. The scoring never rewards it:

- Gold `NEEDS_REVIEW` records are **excluded** from stage3 (`scoring.py:77`) and cannot
  enter end-to-end (they have `has_defect == false`).
- For those ~20 records, the **only** weighted contribution is their **category** in
  stage1 macro-F1.
- Escalating a record that gold says was comparable costs us: `has_defect` false → a
  false negative in stage3 if it was defective, and a failure in end-to-end.

**So over-escalation is expensive and under-escalation is nearly free.** This does not
mean we should abandon `CANNOT_DETERMINE` — it is why the design is correct and the
system is trustworthy, and the brief grades reliability separately for exactly that
reason. But it must be a **conscious** trade, and it argues for tuning the grey band
narrow rather than wide. Spec Open Item 8 (measure grey-band volume before tuning) just
became the highest-value measurement we can make.

### 9.3 `end_to_end` demands exact `defect_fields` equality — and it re-prices our C3 decision

```python
fields_ok = set(s.get("defect_fields", [])) == set(t["defect_fields"])
```

Our M11 change 4 (a confirmed `MISMATCH` outranks `CANNOT_DETERMINE`) lets a partially
unreadable record still report `MISMATCH` and therefore still score. That is worth real
points — **but only when the unresolved field is not itself a gold defect.** If gold says
`{consignee, gross_weight_kg}` and we report `{consignee}` because the weight was
unreadable, exact equality fails and we score **zero** on the headline axis for that
record, exactly as if we had missed it entirely. Partial credit does not exist here.
`field_f1` measures partial overlap, but it is diagnostic and unweighted.

### 9.4 The scoreboard is an unlimited, richly instrumented feedback loop

No rate limit, no cap, no auth. Every `/submit` returns the **confusion matrix** and
per-category `tp/fp/fn`. We can submit after every change and see exactly which category
pairs we are confusing. This is far better than the single number the stage-2 gate
anticipated — the baseline should be recorded alongside the confusion matrix, not just
`final_score`.

### 9.5 Our stage-2 validator is load-bearing, not ceremonial

The server validates almost nothing. A submission with a typo'd status, a wrong field
name, or missing records is accepted and silently scored as wrong. Every guard in
`test_pipeline_and_submission.py` is therefore catching something the server never will.

### 9.6 Concrete follow-ups

1. Move the bundle out of the repo (§7) — awaiting instruction.
2. `LoaderInbox("http://localhost:8080")` for `--server-url`; no adapter change needed.
3. Record the baseline as `final_score` **plus** the stage1 confusion matrix.
4. Consider emitting the optional `decided_by` field (`"rule"` / `"model"`) — it is read
   by `score_stage1` for a `rule_pct` diagnostic. Unscored, but free insight into how much
   the structural layer is carrying. It is an extra key, so it needs a deliberate decision
   about our fixed-five-key entry rule before we add it.
