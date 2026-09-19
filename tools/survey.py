import json, os, glob, collections

SKIP = {'.git', '__pycache__', 'node_modules'}

def walk():
    for d, subs, files in os.walk('.'):
        subs[:] = [s for s in subs if s not in SKIP]
        for f in files:
            yield os.path.join(d, f)

print("=" * 64, "\n1. FILE TYPE CENSUS\n", "=" * 64)
ext, sample = collections.Counter(), {}
for p in walk():
    e = os.path.splitext(p)[1].lower() or "(none)"
    ext[e] += 1
    sample.setdefault(e, p)
for e, c in ext.most_common():
    print(f"{c:6d}  {e:8s}  e.g. {sample[e]}")

print("\n" + "=" * 64, "\n2. EMAIL RECORDS\n", "=" * 64)
cands = [p for p in walk() if p.endswith('.json') and 'submission' not in p.lower()]
print("candidate json files:", len(cands))
for p in cands[:3]:
    print(" ", p)

records = []
for p in cands:
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception as ex:
        print("PARSE FAIL", p, ex); continue
    records.extend(d if isinstance(d, list) else [d])

print("total email records:", len(records))
if records:
    keys = collections.Counter()
    for r in records:
        if isinstance(r, dict):
            keys.update(r.keys())
    print("\nKEYS (key: how many records have it):")
    for k, c in keys.most_common():
        t = type(next(r[k] for r in records if isinstance(r, dict) and k in r)).__name__
        print(f"  {k:24s} {c:5d}  type={t}")
    print("\nFULL FIRST RECORD:")
    print(json.dumps(records[0], indent=2)[:2500])

    print("\nDISTINCT VALUES for short string fields (<=60 chars, <=15 distinct):")
    for k in keys:
        vals = {str(r[k]) for r in records if isinstance(r, dict) and k in r
                and isinstance(r[k], str) and len(r[k]) <= 60}
        if 0 < len(vals) <= 15:
            print(f"  {k}: {sorted(vals)}")

    print("\nATTACHMENT COUNT PER EMAIL:")
    for k in keys:
        if any(isinstance(r.get(k), list) for r in records if isinstance(r, dict)):
            dist = collections.Counter(
                len(r[k]) for r in records if isinstance(r, dict) and isinstance(r.get(k), list))
            print(f"  field '{k}': {dict(sorted(dist.items()))}")
            for r in records:
                if isinstance(r, dict) and r.get(k):
                    print(f"  example '{k}' value: {json.dumps(r[k])[:400]}")
                    break

print("\n" + "=" * 64, "\n3. SAMPLE SUBMISSION\n", "=" * 64)
subs = [p for p in walk() if 'submission' in os.path.basename(p).lower()]
for p in subs:
    print("FILE:", p)
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception as ex:
        print("  PARSE FAIL", ex); continue
    print("  top-level type:", type(d).__name__)
    if isinstance(d, dict):
        print("  number of entries:", len(d))
        for i, (k, v) in enumerate(d.items()):
            if i >= 3: break
            print(f"  KEY: {k}\n  VALUE: {json.dumps(v, indent=2)[:900]}")
    else:
        print(json.dumps(d, indent=2)[:1500])

print("\n" + "=" * 64, "\n4. ATTACHMENT FILES\n", "=" * 64)
atts = [p for p in walk() if not p.endswith(('.py', '.json', '.md', '.txt.bak'))
        and '/inbox' not in p.replace('\\', '/')]
by_ext = collections.defaultdict(list)
for p in atts:
    by_ext[os.path.splitext(p)[1].lower()].append(p)
for e, ps in sorted(by_ext.items()):
    print(f"\n{e}  ({len(ps)} files)")
    for p in ps[:3]:
        print("   ", p, f"({os.path.getsize(p)} bytes)")
