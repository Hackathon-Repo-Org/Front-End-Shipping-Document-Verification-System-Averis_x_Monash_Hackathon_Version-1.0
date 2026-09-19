"""Bucket A/B/C analysis for Phase 5 port resolution. Reads the corpus only."""
import collections
import dataclasses
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from shipdoc.config import load_config
from shipdoc.ingest.loader_port import LoaderInbox
from shipdoc.pipeline import run_corpus
from shipdoc.types import Verdict

PORTS = ("port_of_loading", "port_of_discharge")

cfg_off = load_config(ROOT / "config")
cfg_on = dataclasses.replace(
    cfg_off, flags=dataclasses.replace(cfg_off.flags, port_resolution_enabled=True))
ib = LoaderInbox(str(ROOT / "dataset"))

runs = {}
for label, cfg in (("off", cfg_off), ("on", cfg_on)):
    r = run_corpus(ib, cfg, llm=None, decisions={}, cache_dir=str(ROOT / "output" / "cache"))
    runs[label] = {rec.email_id: rec for rec in r["records"]}

buckets = {"A": [], "B": [], "C": [], "other": []}
unresolved = collections.Counter()

for eid, rec_on in runs["on"].items():
    rec_off = runs["off"].get(eid)
    if rec_off is None:
        continue
    for f in PORTS:
        c_on, c_off = rec_on.comparisons.get(f), rec_off.comparisons.get(f)
        if not c_on or not c_off:
            continue
        v_on, v_off = c_on.verdict, c_off.verdict
        si = c_on.si.raw_text if c_on.si else None
        bl = c_on.bl.raw_text if c_on.bl else None

        if "unresolved" in (c_on.detail or ""):
            for side in (si, bl):
                if side:
                    unresolved[side.strip()] += 1

        if v_on == v_off:
            continue
        row = {"email_id": eid, "field": f, "off": v_off.value, "on": v_on.value,
               "si_raw": si, "bl_raw": bl, "detail_on": c_on.detail,
               "detail_off": c_off.detail}
        if v_off is Verdict.CANNOT_DETERMINE and v_on is Verdict.MATCH:
            buckets["A"].append(row)
        elif v_off is Verdict.CANNOT_DETERMINE and v_on is Verdict.MISMATCH:
            buckets["B"].append(row)
        elif {v_off, v_on} == {Verdict.MATCH, Verdict.MISMATCH}:
            buckets["C"].append(row)
        else:
            buckets["other"].append(row)

print("=" * 72)
print("PHASE 5 BUCKET ANALYSIS — port field verdicts, resolver OFF -> ON")
print("=" * 72)
for k in ("A", "B", "C", "other"):
    label = {"A": "CANNOT_DETERMINE -> MATCH      (expected)",
             "B": "CANNOT_DETERMINE -> MISMATCH   (expected)",
             "C": "MATCH <-> MISMATCH             (ALARM)",
             "other": "other transitions              (needs explanation)"}[k]
    print(f"  bucket {k}: {len(buckets[k]):3d}   {label}")

for k in ("C", "other"):
    if buckets[k]:
        print(f"\n--- EVERY bucket {k} entry, in full ---")
        for row in buckets[k]:
            print(f"  {row['email_id']} / {row['field']}: {row['off']} -> {row['on']}")
            print(f"      SI raw : {row['si_raw']!r}")
            print(f"      BL raw : {row['bl_raw']!r}")
            print(f"      OFF    : {row['detail_off']}")
            print(f"      ON     : {row['detail_on']}")

print("\n--- top 20 unresolved port strings by frequency ---")
for s, n in unresolved.most_common(20):
    print(f"  {n:3d}  {s!r}")
print(f"  ({len(unresolved)} distinct unresolved strings)")

out = ROOT / "BACKUP" / "2026-09-19" / "phase5"
out.mkdir(parents=True, exist_ok=True)
(out / "bucket_analysis.json").write_text(
    json.dumps({"buckets": buckets, "unresolved_top": unresolved.most_common(50)},
               indent=2), encoding="utf-8")
print(f"\nwritten -> {out / 'bucket_analysis.json'}")
