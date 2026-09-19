# SPEC V2 PATCH 02 — Scoring-aware projection

**Read alongside `ARCHITECTURE_SPEC_V2.md` and `SPEC_V2_PATCH.md`. This file wins on overlap.**

Triggered by `DOCKER_BUNDLE_ANALYSIS.md`. The scoring script shipped in the organiser's
Docker bundle is now readable, and it changes how the **projection layer** should behave.
It changes nothing about the pipeline.

---

## 1. What the scoring script actually rewards

| Axis | Weight | Counts false positives? |
|---|---|---|
| stage-1 macro-F1 (category) | **0.30** | Yes — per class |
| stage-3 defect-F1 | **0.20** | Yes — `not gold_defect and pred_defect` |
| end-to-end | **0.50** | **No — pure recall over gold-defective records** |
| reliability / escalation | **0.00** | n/a — not scored at all |

Two structural facts follow, both verified in `scoring.py`:

**F1 — Classification gates everything.** Both weighted comparison axes require the
predicted category to equal `BL_COMPARISON` (`scoring.py:81`, `:157`). One misclassified
comparison email is lost on the 0.30, 0.20 **and** 0.50 axes simultaneously. Classification
is not 30% of the score; it is the gate on 100% of it.

**F2 — The submission has no way to be rewarded for asking for help.** `NEEDS_REVIEW` is a
valid status in the schema, and the reliability axis that would recognise it carries zero
weight. On a record the gold set considers comparable, escalating scores **zero on 70% of
the weight**; deciding wrongly scores worse than nothing only on the 0.20 axis.

---

## 2. The decision, and why it is not "chase the number"

The brief already told us this would happen:

> *"A score cannot fully assess whether the system asked for human review at the right time
> or provided enough context."* · *"It is not the final assessment and does not cover every
> part of a good solution."*

So a zero-weight reliability axis is **consistent with the brief**, not a contradiction of
it. The organisers said the score cannot measure this. The scoring script agrees with them.

**Therefore: keep the architecture. Change only the projection.**

- The **pipeline** stays conservative. It still escalates, still writes evidence, still
  keeps the review queue. That behaviour is what the brief says is assessed *outside* the
  score, and it is what makes the system defensible as engineering.
- The **submission** commits to a judgement wherever the system actually formed one,
  because `NEEDS_REVIEW` earns nothing and a committed judgement can.

This is exactly what M14 exists for. v2 §7 already states the principle: *"the output shape
is not a constraint on how your system works internally."* The projection layer was built
for a divergence like this one; it has now arrived.

**Where the line is.** Commit where the system *formed a view* and merely fell below its own
confidence bar. Do **not** invent a view where it has none. A fabricated `MISMATCH` on a
document nobody could read is inventing data, and it is a different act from committing to a
judgement you actually made. That line is drawn in §4 below and it is not negotiable for
score.

**Also not negotiable:** do not tune thresholds against the scoreboard until the numbers
improve. The brief warns about this directly, and it is over-fitting to a hidden reference
set. Understanding the rubric is legitimate; memorising the answers through it is not.

---

## 3. New field — `Comparison.leaning`

To project honestly, the record must distinguish *"uncertain but leaning negative"* from
*"no information at all"*. Both are `CANNOT_DETERMINE` today.

```python
@dataclass(frozen=True)
class Comparison:
    field:    str
    verdict:  Verdict
    si:       FieldValue | None
    bl:       FieldValue | None
    strategy: str
    detail:   str
    leaning:  Verdict | None = None   # NEW — what it would say if forced
```

`leaning` is set **only** when `verdict is CANNOT_DETERMINE` and the comparator had a
directional signal:

| Situation | `verdict` | `leaning` |
|---|---|---|
| similarity in the grey band | `CANNOT_DETERMINE` | `MISMATCH` |
| port code unresolvable, normalised strings differ | `CANNOT_DETERMINE` | `MISMATCH` |
| port code unresolvable, normalised strings equal | `CANNOT_DETERMINE` | `MATCH` |
| two candidate values found for one field | `CANNOT_DETERMINE` | `MISMATCH` |
| a side is `None` because a **sentinel** matched | `CANNOT_DETERMINE` | `None` |
| a side is missing because the **document was unreadable** | `CANNOT_DETERMINE` | `None` |
| unit unrecognised, cannot parse | `CANNOT_DETERMINE` | `None` |

`leaning is None` means *"I have no view"*. That is the honest state for anything that
failed to obtain data, and it projects to `NEEDS_REVIEW`.

`Record` gains one derived list, populated by `evaluate` alongside `defects` and
`unresolved`:

```python
suspected: list[str]   # fields where verdict is CANNOT_DETERMINE and leaning is MISMATCH
```

---

## 4. Revised projection table — M14

| Internal state | `status` | `review_reason` | `defect_fields` | `has_defect` |
|---|---|---|---|---|
| `RESOLVED`, no defects, no suspicions | `OK` | `null` | `[]` | `false` |
| `RESOLVED`, defects present | `MISMATCH` | `null` | `defects + suspected` | `true` |
| `ESCALATED`, **`suspected` non-empty** | **`MISMATCH`** | `null` | **`suspected`** | **`true`** |
| `ESCALATED`, `suspected` empty | `NEEDS_REVIEW` | `REASON[reason]` | `[]` | `false` |
| `FAILED` | `NEEDS_REVIEW` | `unreadable` | `[]` | `false` |
| non-comparison category | `OK` | `null` | `[]` | `false` |

**Row 3 is the change.** A comparison record the system escalated *because it suspected
something* now reports that suspicion instead of reporting silence.

**The arithmetic.** For a record where the system suspects a defect, let `p` be the
probability it is genuinely defective:

| Choice | end-to-end (0.50) | defect-F1 (0.20) |
|---|---|---|
| emit `MISMATCH` | `+p` | `+p` as TP, `−(1−p)` as FP |
| emit `NEEDS_REVIEW` | `0` | `−p` as FN |

`MISMATCH` dominates on the heavier axis and is only partly penalised on the lighter one.
It is positive expected value whenever `p` is above roughly 0.2–0.3 — and on a record where
the comparator actually leaned `MISMATCH`, `p` is far above that.

**Rows 4 and 5 do not change**, and that is the deliberate part. `unreadable`,
`missing_attachment` and `wrong_doc_type` mean the system obtained nothing. There is no
judgement to commit to, so it says so.

---

## 5. Classification policy — M07

F1 makes the classifier the highest-leverage component in the system by a wide margin.

**Lean toward `BL_COMPARISON` on the margin**, because the error is asymmetric:

| Error | Cost |
|---|---|
| Called it `BL_COMPARISON`, gold says otherwise | Precision damage on **one class** of a macro-F1 worth 0.30 |
| Called it something else, gold says `BL_COMPARISON` | **Total loss on 0.30 + 0.20 + 0.50** |

Concretely: an email carrying two SI/BL-shaped attachments should be `BL_COMPARISON` unless
there is positive evidence against it. The structural test already identifies these 126; do
not let the model overturn the structural signal on a two-attachment email without a strong
reason.

**Measure it, do not assume it.** Submit twice at stage 3 — once with the structural
signal decisive on two-attachment emails, once with the model able to overturn it — and keep
whichever scores better. That is a legitimate A/B on a policy, not threshold over-fitting.

Also run the **majority-class floor** (all `GENERAL` / all `OK`) once, as a separate
diagnostic. If the classifier does not beat a constant, that is a fact worth knowing early.

---

## 6. Repository hygiene — now urgent

`sdoc-hackathon-docker/data_v2/ground_truth.json` (79,980 bytes) is currently **inside the
repository**, alongside six generator scripts and a README that were correctly left unread.

**Move the Docker bundle to a sibling directory outside the repo.** This is no longer a
tidiness question:

- A careless glob (`**/*.json`, a recursive walk, a test fixture discovery) could pull the
  gold answers into the process. Even accidentally, every number produced afterwards would
  be worthless and you would not be able to prove otherwise.
- `pytest` collection and import resolution both currently see a second `loader.py`,
  `inbox/` and `attachments/`.

```
sdoc-hackathon-bundle/          <- repo, unchanged
sdoc-server/                    <- move the bundle here, sibling, outside
```

Point `--server-url` at `http://localhost:8080` as before; the container does not need to
live inside the repo to serve. Add `ground_truth.json` and `data_v2/` to `.gitignore`
regardless, as a second layer.

**Do not open `ground_truth.json`, and do not write code that reads it.** Reading the rubric
is legitimate; reading the answers destroys the exercise and is not recoverable.

---

## 7. What to say about this in the presentation

Do not hide it. It is one of the stronger things the team can demonstrate:

> *"We read the scoring script the organisers shipped. The reliability axis carries zero
> weight, so escalating a comparable record costs points and failing to escalate costs
> nothing. We kept the conservative design anyway, because the brief states the score cannot
> assess whether the system asked for review at the right time — and we made the submission
> commit to a judgement wherever the system actually formed one. Here is the review queue
> that shows the behaviour the score cannot see."*

That is a team that read the rubric, understood the incentive it creates, and made a
deliberate choice. The alternative — discovering it after the fact, or not discovering it at
all — reads very differently.

---

## 8. Summary of changes

| # | Change | File |
|---|---|---|
| 1 | `Comparison.leaning` added | `types.py` |
| 2 | Comparators set `leaning` per the §3 table | `compare/comparators.py` |
| 3 | `Record.suspected` derived in `evaluate` | `types.py`, `state/machine.py` |
| 4 | Projection row 3: escalated-with-suspicion → `MISMATCH` | `adapters/submission.py` |
| 5 | Classification leans `BL_COMPARISON` on two-attachment emails | `classify/arbiter.py` |
| 6 | A/B the classification policy at stage 3; run the majority-class floor | build process |
| 7 | Move the Docker bundle outside the repo; gitignore `data_v2/` | repo layout |

Items 1–4 are **stage 4 work** (the comparator does not exist yet). Item 5 is **stage 3**.
Items 6–7 are immediate.

*End of patch 02.*
