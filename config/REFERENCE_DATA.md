# Reference data provenance

## `unlocode.csv.gz` — UN/LOCODE code list

| | |
|---|---|
| **Dataset** | UN/LOCODE — United Nations Code for Trade and Transport Locations |
| **Authority** | UNECE (United Nations Economic Commission for Europe) |
| **Obtained from** | `https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv` |
| **Mirror repo** | https://github.com/datasets/un-locode (Datahub / Frictionless Data) |
| **Mirror commit** | `b1309b37edea63334a819a78c22b8967f61c37ad`, committed 2026-07-27 |
| **Retrieved** | 2026-09-19 |
| **Licence** | Open Data Commons Public Domain Dedication and Licence (**PDDL v1.0**) — public domain, freely redistributable |
| **Rows** | 116,213 |
| **Size** | 7,287,475 bytes raw · 2,046,478 bytes gzipped |
| **sha256 (raw CSV)** | `014d5139df76894a89f7eeb529723417e790129a5c7ea3b3dac38c34a03455c1` |
| **sha256 (.gz as shipped)** | `9a312aa67e6e5fbf4945ccc329fa49bb27f9b728e378d1e60f297cd1092f36e4` |

**Edition.** The mirror does not carry a UNECE edition number in the data or its
README, so none can be stated honestly here. The mirror commit hash and retrieval
date above are the reproducible identifiers. UNECE publishes roughly twice a year;
`unece.org` returns HTTP 403 to non-browser clients, which is why the mirror was used.

**No filter applied.** The complete code list is shipped. At 1.95 MB gzipped it is
well inside the size budget, so there was no reason to subset it — and any filter
(for example, keeping only rows whose `Function` marks a seaport) would be a judgement
that could silently drop a location the corpus actually uses.

**Columns.** `Change, Country, Location, Name, NameWoDiacritics, Subdivision, Status,
Function, Date, IATA, Coordinates, Remarks`. A LOCODE is `Country` + `Location`
concatenated, e.g. `MY` + `PKG` = `MYPKG`. The resolver uses `Country`, `Location`,
`Name` and `NameWoDiacritics`; the rest is carried but unused.

## Updating

```bash
curl -sL -o code-list.csv \
  https://raw.githubusercontent.com/datasets/un-locode/main/data/code-list.csv
gzip -9 -c code-list.csv > config/unlocode.csv.gz
```

Then re-run the pipeline and diff the submission. **A reference-data update is a
behaviour change**: record which records moved and why, exactly as Phase 5 did.

## How it is loaded

`config/pipeline.yaml` names the file under `reference.unlocode`, resolved relative to
the config directory. It is read once per run, at startup, from disk — **no network
call at runtime**. If the file is absent the resolver degrades to shape-recognition
only, which is precisely the behaviour that existed before this data was added.
