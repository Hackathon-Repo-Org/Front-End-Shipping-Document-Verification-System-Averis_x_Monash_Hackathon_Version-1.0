# Adversarial fixtures — emails 997, 998, 999

**These are synthetic. They were hand-written by this team to attack known seams in
the system. They are NOT from the organisers, they are NOT part of the 520-email
corpus, and there is no official answer key for them.**

The expectations below are *our* reasoning about what a correct system should report,
written down so they can be argued with. Where our expectation differs from what the
system does, the difference is stated rather than hidden.

They exist because the published precision of 1.000 was measured on the provided
corpus only. A number measured on one corpus is a fact about that corpus. These three
emails are the cheapest available evidence about everything else.

## How to run them

```powershell
python -m shipdoc --source tests\fixtures\adversarial --out output_adversarial
python -m shipdoc inspect email_997 --source tests\fixtures\adversarial
```

The regression test is `tests/integration/test_adversarial.py`, which asserts the
per-field expectations below and runs in CI alongside the 520.

---

## email_997 — six traps on one SI/BL pair

A well-formed comparison request. Every field is labelled on both documents, so
nothing here is an extraction problem: each line tests one *comparison* rule.

| Field | SI | BL | Expected | Why |
|---|---|---|---|---|
| `shipper` | `MEGA RUBBER GLOVE SDN BHD` | `MEGA RUBBER GLOVE SDN. BHD.` | **match** | The legal suffix differs only in punctuation. `normalise_party_name` canonicalises the *spelling* of a suffix; it must never equate two *different* suffixes. |
| `consignee` | `NORDIC HEALTHCARE SERVICES GMBH` | same | **match** | Control. |
| `notify_party` | `SAME AS CONSIGNEE` | `NORDIC HEALTHCARE SERVICES GMBH` | **match** | Referential value. It resolves to this document's own consignee, which is what the BL spells out. Comparing it as a literal company name is a fabricated defect. |
| `port_of_loading` | `PORT KLANG (MYPKG)` | `HAMBURG, GERMANY (DEHAM)` | **MISMATCH** | Genuine. The two ports are **swapped** between the documents — a real and expensive error. |
| `port_of_discharge` | `HAMBURG, GERMANY (DEHAM)` | `PORT KLANG (MYPKG)` | **MISMATCH** | The other half of the swap. |
| `container_count` | `2 x 40'HC` | `2 x 4O'HC` | **match** | The *count* is 2 on both sides, and `container_count` is the count. The letter-`O`-for-zero homoglyph corrupts the container **size**, which this system does not model. See "Known gap" below. |
| `gross_weight_kg` | `22,450.50 KGS` | `22.450,50 KGS` | **match** | European vs US decimal separators, identical value. `parse_quantity` must read separator *order*, not assume a convention. |

**Correct answer:** `BL_COMPARISON`, `MISMATCH`, defect fields exactly
`{port_of_loading, port_of_discharge}`.

**Known gap (not a bug):** `2 x 4O'HC` vs `2 x 40'HC` is a real defect a human would
catch, and we report `match`. The field is defined as a count, so the verdict is
correct *for the field as defined*. Detecting it requires adding container **size** as
an eighth compared field. That is a field-definition change, recorded in
`HANDOVER.md`, not something to patch into the count comparator.

---

## email_998 — the subject line lies

No attachments at all. The subject says `URGENT: INVOICE DISPUTE & REMITTANCE
ADVICE`; the body says:

> "we noticed a critical issue on the draft BL … **Please immediately audit the draft
> Bill of Lading against our SI** and confirm the discrepancies before vessel
> cut-off."
>
> "(Apologies, I forgot to attach the files in this email—will forward them in 5
> minutes)."

**Correct answer:** `BL_COMPARISON`. The body carries an explicit, unambiguous
instruction to compare a BL against an SI; the subject describes a *different* matter
in the same thread. Real email works this way — subjects are stale, bodies are
current.

The second question is what status follows, and here the expectation written before
the run turned out to be wrong. It is left in, corrected, rather than quietly
replaced.

**Expected before running:** `awaiting_documents` — the sender says the files are
coming in five minutes, so nothing is missing yet.

**What actually happens:** `missing_attachment`, escalated. The awaiting-docs rule
now *does* run on this record — before Fix 3 it never did, because the category
short-circuited first — and it declines. `_EXPECTED_PRESENT` contains
`\battach\w*\b`, which matches "forgot to **attach** the files". That pattern is
meant to catch a sender who *believes* they attached something; it cannot see that
this one is a *negated* attachment claim.

**Which is correct?** Defensible either way, and the fixture asserts the measured
behaviour. `missing_attachment` puts an urgent, explicit audit request with nothing
to audit in front of a human, which is not a bad outcome. But the classification is
being made for the wrong reason, and the negated-attachment gap is recorded in
`HANDOVER.md` as a known limitation rather than patched — `_EXPECTED_PRESENT` is
load-bearing for the 20/20 planted edge cases and is not something to tune against a
single synthetic email.

This was the highest-risk fix in Phase 10: classification gates all three weighted
axes.

---

## email_999 — sentinels, bare port codes, and an anti-synonym trap

| Field | SI | BL | Expected | Why |
|---|---|---|---|---|
| `shipper` | `EVERGREEN FIBREBOARD BHD` + address | same | **match** | Control, with an address continuation. |
| `consignee` | `TO THE ORDER OF TOYOTA TSUSHO CORP` | same | **match** | `To the Order of` is a label synonym elsewhere; here it is part of the *value* and must not be eaten. |
| `notify_party` | `TOYOTA LOGISTICS SERVICE JAPAN` | `_______` | **cannot determine** | A blank-line sentinel. The BL has not been filled in, which is a reviewer's call, not a confirmed contradiction. |
| `port_of_loading` | `TANJUNG PELEPAS (MYTPP)` | `MYTPP` | **match** *(needs port resolution)* | Same port, written as a bare UN/LOCODE on one side. Port resolution is switched **off** by measurement, so the system currently reports a defect here. This is a known, documented false positive — see `docs/decisions/port-resolution.md`. |
| `port_of_discharge` | `NAGOYA, JAPAN (JPNGO)` | `JPNGO` | **match** *(needs port resolution)* | Same. |
| `container_count` | `3 x 40'HC` | `Containers: 3 x 40'HC` | **match** | Character-identical values. The BL's label is the bare word `Containers:`. |
| `gross_weight_kg` | `GROSS WEIGHT: 45,120.00 KGS` | `Gross Weight (KG): N/A` | **cannot determine** | The BL's gross weight is a sentinel. **The trap:** the BL also carries `NET WEIGHT: 45,120.00 KGS` — the SI's *gross* figure sitting under a *net* label. A system that treats `WEIGHT` as one field reports a confident `match` on two different quantities. The anti-synonym list must refuse it. |

**Correct answer:** `BL_COMPARISON`, `NEEDS_REVIEW` — two unresolvable sentinels and
nothing confirmed against them.

The BL is titled `DRAFT BILL OF LADING`, which must still be recognised as a BL.

---

## What each fixture is protecting

| | 997 | 998 | 999 |
|---|---|---|---|
| party-suffix punctuation | ✔ | | |
| referential values (`SAME AS …`) | ✔ | | |
| decimal-separator convention | ✔ | | |
| genuine defect detection (port swap) | ✔ | | |
| body intent over subject line | | ✔ | |
| awaiting-documents | | ✔ | |
| sentinel never compares equal | | | ✔ |
| anti-synonym (net vs gross) | | | ✔ |
| unseen label ≠ absent value | | | ✔ |
| bare UN/LOCODE | | | ✔ |
