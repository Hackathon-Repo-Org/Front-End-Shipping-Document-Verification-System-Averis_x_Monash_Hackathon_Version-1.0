# Projection rows 2 and 3 — examined against the answer key, both KEPT

The teammate review objects to both. Both were measured rather than argued, and both
survive. This file is the evidence, so neither is re-litigated.

## Row 2 — appending `suspected` to confirmed defects: KEEP (review objection B4)

`RESOLVED` with defects emits `defects + suspected`. Removing the append was tried
(Phase 7 Fix 1) and **reverted**:

| | end-to-end | final |
|---|---|---|
| with the append | 35/46 | **0.8582** |
| `defects` only | **30/46** | 0.8039 |

**Why it is correct.** On **10 records** `defects ∪ suspected` equals the gold defect
set *exactly*, while `defects` alone does not — the suspicion IS the defect there:

```
email_004  defects=['notify_party']  + suspected=['consignee']             == gold
email_145  defects=[]                + suspected=['shipper']               == gold
email_300  defects=[]                + suspected=['notify_party','shipper'] == gold
email_334  defects=[]                + suspected=['consignee','shipper']   == gold
email_144, 225, 256, 312, 324, 379 — same pattern
```

Five were already scoring end-to-end, which is the 35 → 30 drop.

**The finding that motivated removing it was wrong.** Phase 6's "Q1" reported 6 records
where appending `suspected` broke an exactly-correct defect set. Re-derived: those 6
records have `suspected == []`. The append touched none of them. Their over-wide defect
sets came from `rec.defects`, caused by the docx label bug (see below). Q1's query
tested only "gold ⊂ ours" and attributed the cause without checking it.

## Row 3 — escalated-with-suspicion reported as MISMATCH: KEEP

Proposed restriction: fire row 3 only for grey-band similarity, and project
`unreadable` / `missing_value` / `wrong_doc_type` / `missing_attachment` as
NEEDS_REVIEW regardless of leaning. **Cancelled before implementation**, on this split:

> Query: row 3 fires iff `rec.state is ESCALATED and rec.suspected`; row 2 iff
> `rec.state is RESOLVED and rec.defects`. Both emit `status=MISMATCH`, so
> `submission.json` alone cannot separate them — the split needs internal record state
> joined to the answer key. The reconstructed run was asserted byte-identical to the
> scored `submission.json` before any of it was trusted.

**6 records fire row 3. 5 gold-defective, 1 gold-clean.** All six escalated under the
same reason, `err_no_value`:

| reason | gold-defective | gold-clean |
|---|---|---|
| `err_no_value` | 5 — `email_145`, `225`, `300`, `334`, `379` | 1 — `email_512` |

Zero row-3 records come from `unreadable`, `wrong_doc_type` or `missing_attachment`:
those paths leave `suspected` empty by construction, exactly as patch 02 §4 intended.

The proposed restriction names `missing_value`, so it would have suppressed **all six**
— trading 5 gains for 1 false-positive removal. Net **−4** gold-defective records on the
0.50 axis.

The one false positive, `email_512`, is a scanned PDF, and is addressed by the scan
policy (review item B2) rather than by weakening row 3.

## Also recorded: row 2's 8 false defects are NOT the docx records

> Query: `row2_false := RESOLVED and rec.defects and not gt[e]['has_defect']`;
> `docx := BL attachment filename ends _BL.docx`.

```
row2_false (8): 055, 462, 514, 516, 517, 518, 519, 520
docx       (8): 055, 097, 107, 291, 302, 354, 435, 462
intersection (2): 055, 462
```

Two distinct populations that happen to be the same size. The 6 non-docx false defects
are the scan group (`514`) and the placeholder group (`516`–`520`).
