# Shipping Document Verification

When a freight customer sends a **Shipping Instruction** (SI) — what they want shipped,
to whom, to which port — the carrier replies with a **draft Bill of Lading** (BL), the
document of title that actually moves the cargo. Someone has to check that the draft
says what the customer asked for, because a wrong consignee or a wrong discharge port
on a BL is expensive and slow to unwind once the vessel has sailed.

This system reads a shipping team's inbox, works out which emails are asking for that
check, and compares **seven fields** between the SI and the draft BL: shipper,
consignee, notify party, port of loading, port of discharge, container count and gross
weight. Every field gets one of three verdicts — **match**, **mismatch**, or
**cannot determine** — and that third verdict is the point: where the documents are
unreadable, the wrong document was attached, or a value was left blank, the record is
escalated to a human with the evidence attached rather than guessed at.

## Current score

Measured **2026-09-20** against the organisers' own `scoring.py`, imported directly
rather than reimplemented.

| Axis | Weight | Score |
|---|---|---|
| Stage 1 — email classification (macro-F1) | 0.30 | 0.9526 |
| Stage 3 — defect detection (F1) | 0.20 | 0.9890 · precision **1.000** |
| End-to-end — defects caught exactly | 0.50 | 0.9348 — **43/46** |
| Reliability — escalation (diagnostic, unweighted) | 0.00 | recall **1.000** |
| **Final** | | **0.9510** |

All **20/20** planted edge cases correct. 577 tests pass. Two runs produce
byte-identical output.

**On that precision of 1.000:** it is measured on the provided 520-email corpus, and
it is a fact about that corpus rather than a property of the system — on three
hand-written adversarial emails the same build reported four false defects before
Phase 10 and two after, both of which are the known bare-UN/LOCODE case. Those three
emails now live in `tests/fixtures/adversarial/` and run in CI alongside the 520.

## Quick start

Python 3.12+. Nothing else — no Docker, no GPU, no model download.

```powershell
git clone https://github.com/Hackathon-Repo-Org/Shipping-Document-Verification-System-Averis_x_Monash_Hackathon.git
cd Shipping-Document-Verification-System-Averis_x_Monash_Hackathon
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m shipdoc doctor
```

`doctor` checks the install, the corpus, the config and a live sample run, then prints
`RESULT: PASS`. Optional capabilities it cannot find (OCR, the LLM) are reported as
`[--  ]` and are **expected to be missing** — the system runs without them and says
what it lost.

Then:

```powershell
python -m shipdoc                      # full run -> output\
python -m shipdoc inspect email_013    # one record, seven fields, side by side
python -m pytest -q                    # 577 tests
```

## Why the model cache is committed

`cache/llm/` holds this system's **own classifier outputs**, produced at temperature 0.
Committing it means a fresh clone reproduces the published score in seconds with no
Ollama installed, and it is what makes runs byte-identical — temperature 0 alone does
not guarantee that, because batching and GPU reduction order vary between calls.

**It is not the answer key and contains no gold labels.** Each filename is a
`sha256(model + prompt_version + prompt)` — irreversible, so no email text is stored —
and each file's entire contents is one of the five category strings this system
predicted. Nothing in it is derived from the organisers' labels. The model name and
prompt version are recorded in `cache/llm/MANIFEST.json`, and they are part of every
cache key, so a cache built by a different model misses and re-queries rather than
silently returning the wrong answers.

Checkable rather than asserted — clear it and rebuild (needs Ollama and
`qwen2.5:7b-instruct`, ~15 minutes):

```powershell
Remove-Item -Recurse -Force cache\llm
python -m shipdoc                      # re-queries the model, rewrites the cache
```

## Documentation

| File | For |
|---|---|
| **[SETUP.md](SETUP.md)** | Installing, in three tiers. Most people need only Tier 1. |
| **[TESTING.md](TESTING.md)** | Testing and inspecting, in six levels, without needing to understand the system. |
| **[HANDOVER.md](HANDOVER.md)** | Current state, what changed, what is known broken. |
| **[docs/spec/](docs/spec/)** | The architecture specification and its patches. |
| **[docs/reports/](docs/reports/)** | Corpus survey, scoring-rubric analysis. |
| **[docs/decisions/](docs/decisions/)** | Why port resolution is off, and why projection rows 2 and 3 were kept — both measured. |

## Not built yet

No API, no web UI, no cloud deployment, no database — everything is files on disk and a
CLI. `python -m shipdoc inspect` is the view a UI would wrap rather than replace.

UN/LOCODE port-code resolution is built, tested and **switched off**: measured against
the answer key it destroyed more real defect detections than it created, because this
corpus writes port defects as a name/code contradiction. The reasoning and the fix
direction are recorded; the flag is one boolean.

A `BACKUP/` directory of superseded specifications and experiment output exists in the
authors' working copy and is deliberately **not published** — nothing was deleted, it
is simply not part of this repository.
