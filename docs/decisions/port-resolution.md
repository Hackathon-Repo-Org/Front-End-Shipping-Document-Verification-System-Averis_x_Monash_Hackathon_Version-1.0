# Phase 5 — UN/LOCODE port resolution: built, measured, switched OFF

**Status: OFF.** `config/pipeline.yaml` → `flags.port_resolution_enabled: false`.
Flip that one boolean to turn it back on. Nothing was deleted; the code, the tests
and the 116,213-row reference table are all still in place.

## What Phase 5 built

A UN/LOCODE resolver (`src/shipdoc/normalise/ports.py`) that turns a port string such
as `CALLAO, PERU (PECLL)` into the code `PECLL`, so two spellings of one port compare
equal. It ships with the complete UNECE code list at `config/unlocode.csv.gz`
(1.95 MB, 116,213 rows, ODC-PDDL licence — provenance in `config/REFERENCE_DATA.md`).

Resolution is exact-match only: a code token confirmed by table membership, or an
exact normalised-name lookup. No fuzzy matching into the table. Unresolvable returns
`None`, which propagates as `CANNOT_DETERMINE` and never as a comparison result.

## Why it is switched off

**It destroys more real defect detections than it creates.** Measured by running the
corpus with the flag off and on and diffing every port-field verdict.

| Bucket | Count | Meaning |
|---|---|---|
| **A** CANNOT_DETERMINE → MATCH | 13 | intended — two spellings of one port |
| **B** CANNOT_DETERMINE → MISMATCH | 3 | intended — genuinely different ports |
| **C** MATCH ↔ MISMATCH | **14** | **alarm — every one is harmful** |
| other (MATCH → CANNOT_DETERMINE) | 18 | coverage gaps; confident correct answers become uncertain |

### The root cause, and it is a design error not a bug

This corpus plants its port defects as a **name/code contradiction**: the document
keeps a stale parenthetical code while the place name changes. Thirteen bucket-C
entries look like this:

```
email_013  port_of_discharge   MISMATCH -> MATCH
    SI : 'MOMBASA, KENYA (KEMBA)'
    BL : 'TUTICORIN, INDIA (KEMBA)'
    OFF: 'MOMBASA' vs 'TUTICORIN', similarity 0.125   <- correctly a defect
    ON : KEMBA vs KEMBA (UN/LOCODE)                   <- declared clean
```

Mombasa and Tuticorin are different ports on different continents. The string
comparator caught it. The resolver's **rule 1 — "a code token, confirmed by table
membership, wins" — throws the name away and reports a match.**

The same mechanism hides inside bucket A, which is not as clean as its count suggests:

```
email_410  SI 'SINGAPORE (SGSIN)'  vs  BL 'PORT KLANG (WESTPORT), MALAYSIA (SGSIN)'  -> MATCH
email_468  SI 'SINGAPORE (SGSIN)'  vs  BL 'RUGAO/NANTONG/SHANGHAI, CHINA (SGSIN)'    -> MATCH
```

Two more destroyed detections. So the true harm is **15 defects lost**, against 11
genuine gains in bucket A and 3 in bucket B.

One bucket-C entry runs the other way and is a false alarm:

```
email_519  port_of_loading   MATCH -> MISMATCH
    SI : 'BUATAN, INDONESIA'          -> name lookup -> IDBUN
    BL : 'BUATAN, INDONESIA (IDBUA)'  -> code token  -> IDBUA
```

Same place, written the same way, two different codes — because one side resolved by
name and the other by code. Mixing resolution paths across the two sides of a
comparison is not safe.

### The fix, when someone picks this up

Do **not** let a code token override a contradicting name. Options, in order of
preference:

1. Resolve **both** sides the same way — by name if both have names, by code only if
   neither has a usable name — and treat a name/code contradiction within one field as
   `CANNOT_DETERMINE` with `leaning=MISMATCH`. It is a real signal that something is
   stale.
2. Or use the code only to *confirm* a name match, never to override a name mismatch.

Either way, re-run the bucket analysis before trusting it.
`docs/decisions/port-resolution-buckets.json` has every entry in machine-readable
form; the script that produced it is `tools/bucket_analysis.py`.

## Coverage — the other reason to wait

The 18 "other" transitions are MATCH → CANNOT_DETERMINE: the table simply does not
contain the string, so a previously confident (and correct) answer becomes uncertain.
Top unresolved port strings by frequency:

| n | string | why |
|---|---|---|
| 13 | `PORT KLANG (WESTPORT), MALAYSIA` | `(WESTPORT)` is a berth, not a LOCODE; the parenthetical breaks the name key |
| 9 | `RUGAO/NANTONG/SHANGHAI, CHINA` | three ports in one field |
| 4 | `HOCHIMINH CITY, VIETNAM` | table has `Ho Chi Minh City`, spaced differently |
| 3 | `HOUSTON, US` | ambiguous — several Houstons |
| 2 | `APAPA, NIGERIA` | not a top-level entry |
| 2 | `YANGON, MYANMAR` | table has `Yangon (Rangoon)` |
| 2 | `NEW YORK, US` | ambiguous — 3 codes |
| 1 | `MOMBASA, KENYA` | not matched after country strip |

8 distinct strings. Most are fixable in the name normaliser rather than the table —
strip a non-LOCODE parenthetical before the name lookup, and handle `A/B/C` multi-port
fields explicitly.

## Two things Phase 5 got wrong procedurally

1. **It never measured anything.** Task D (bucket analysis) and Task E (scoreboard)
   never ran — the run was interrupted first. The bucket table above was produced in
   Phase 6, not Phase 5.
2. **`python -m shipdoc` was silently broken the whole time.** It needs `PYTHONPATH`
   set, and every invocation was redirected to `/dev/null`, so it failed with
   `No module named shipdoc` and left a stale `output/submission.json` in place. The
   "unchanged hash" that made Phase 5 look behaviour-neutral was a Phase 4 file that
   had never been rewritten. Part 1 of Phase 6 fixes this properly with
   `pip install -e .`.

## The flag has two halves — do not gate only one

Port resolution reaches the output through **two** paths:

- `compare/comparators.cmp_port` — the obvious one
- `normalise.PortResolver.identity()` — which returns a LOCODE instead of a place
  name when the table is loaded, changing `FieldValue.normalised` for every resolvable
  port

Gating only the comparator left the second leaking and the pre-Phase-5 hash would not
come back. `Normaliser` now refuses to load the table at all when the flag is off.
`tests/property/test_port_flag.py` pins both halves.

## Fix direction (not implemented)

**Rule 1 — resolve each side TWICE, and distrust a self-contradicting side.**
Resolve once from the name and once from the literal code token in the string. If a
side's name-derived code disagrees with its own literal code, that side is internally
inconsistent and its code is NOT trusted; fall back to the name for that side. Codes
decide only when both sides are internally consistent.

```
MOMBASA, KENYA (KEMBA)  vs  TUTICORIN, INDIA (KEMBA)
  -> TUTICORIN name-resolves to INTUT != KEMBA -> distrust code
  -> compare names -> MISMATCH                        (detection restored)

HOCHIMINH CITY, VIETNAM  vs  HO CHI MINH CITY, VIETNAM (VNSGN)
  -> both internally consistent -> codes agree -> MATCH   (gain preserved)

email_519: BUATAN name->IDBUN, literal IDBUA -> distrust -> names equal
  -> MATCH                                             (false alarm removed)
```

**Rule 2 — resolution may only ADD information.** Separate from rule 1. If resolution
fails, fall back to the string-comparison verdict. It must never turn a MATCH into
CANNOT_DETERMINE — that is exactly what the 18 records in the "other" bucket are, and
it is a straight loss.

Verify against all 16 cases in the bucket tables above before trusting it.

**The flag stays `false` until both rules are implemented and re-measured.**
