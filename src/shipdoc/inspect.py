"""`python -m shipdoc inspect <email_id>` — look at one record.

Prints the seven compared fields side by side: SI value, BL value, verdict, and the
evidence (file plus line or cell) for each. This is TESTING.md level 3, and it is the
view a future web UI wraps in HTML rather than replaces.
"""
from __future__ import annotations

import sys
from pathlib import Path

W_FIELD, W_VAL = 18, 30


def _truncate(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def run(email_id: str, source: str = "dataset", config_dir: str = "config",
        no_llm: bool = False) -> int:
    from shipdoc.config import load_config
    from shipdoc.ingest.loader_port import LoaderInbox
    from shipdoc.pipeline import build_llm, process
    from shipdoc.types import Record, Verdict

    cfg = load_config(Path(config_dir))
    inbox = LoaderInbox(source)

    try:
        emails = {e["email_id"]: e for e in inbox.emails()}
    except Exception as e:
        print(f"shipdoc: could not read the corpus: {e}", file=sys.stderr)
        return 2

    raw = emails.get(email_id)
    if raw is None:
        print(f"shipdoc: no such email: {email_id}", file=sys.stderr)
        near = [k for k in sorted(emails) if k.startswith(email_id[:9])][:5]
        if near:
            print(f"  did you mean: {', '.join(near)}", file=sys.stderr)
        return 2

    # One record needs the same collaborators a full run builds.
    from shipdoc.extract.registry import default_registry
    from shipdoc.normalise import Normaliser
    from shipdoc.normalise.labels import LabelIndex
    from shipdoc import pipeline as pl

    pl._CTX["inbox"] = inbox
    pl._CTX["registry"] = default_registry(ocr_enabled=cfg.flags.ocr_enabled)
    pl._CTX["normaliser"] = Normaliser(cfg)
    pl._CTX["label_index"] = LabelIndex(cfg)
    pl._CTX["roles"] = {}
    pl._CTX["doccache"] = None

    llm = None if no_llm else build_llm(cfg, Path("output"))
    rec = process(Record(email_id=email_id, raw=raw), cfg, llm, {})

    print("=" * 78)
    print(f"{rec.email_id}    category={rec.category}    state={rec.state}")
    print("=" * 78)
    print(f"  from    : {raw.get('from', '')}")
    print(f"  subject : {_truncate(raw.get('subject'), 66)}")
    if rec.reason:
        print(f"  reason  : {rec.reason}")
    atts = raw.get("attachments") or []
    print(f"  attached: {len(atts)}")
    for a in atts:
        doc = next((d for r, d in rec.documents.items()
                    if a.endswith(f"_{r}.txt") or f"_{r}." in a), None)
        state = "read ok" if (doc and doc.ok) else ("no text" if doc else "not extracted")
        print(f"              {a}   [{state}]")

    if not rec.comparisons:
        print()
        print("  No field comparison was performed.")
        print(f"  Why: {rec.reason or 'not a comparison request'}")
        print()
        _print_trace(rec)
        return 0

    print()
    print(f"  {'field':<{W_FIELD}} {'verdict':<10} {'SI (authoritative)':<{W_VAL}} BL")
    print(f"  {'-' * W_FIELD} {'-' * 10} {'-' * W_VAL} {'-' * W_VAL}")

    mark = {Verdict.MATCH: "match", Verdict.MISMATCH: "DEFECT",
            Verdict.CANNOT_DETERMINE: "unknown"}
    for name in cfg.fields:
        c = rec.comparisons.get(name)
        if c is None:
            print(f"  {name:<{W_FIELD}} {'MISSING':<10} (no comparison emitted)")
            continue
        label = mark.get(c.verdict, "?")
        if c.verdict is Verdict.CANNOT_DETERMINE and c.leaning is Verdict.MISMATCH:
            label = "suspect"
        si = _truncate(c.si.raw_text if c.si else "—", W_VAL)
        bl = _truncate(c.bl.raw_text if c.bl else "—", W_VAL)
        print(f"  {name:<{W_FIELD}} {label:<10} {si:<{W_VAL}} {bl}")
        if c.verdict is not Verdict.MATCH:
            print(f"  {'':<{W_FIELD}} {'':<10} {_truncate(c.detail, 58)}")
        # Phase 10 Fix 2. Never let a substituted value look like a read one.
        for role, fv in (("SI", c.si), ("BL", c.bl)):
            if fv is not None and fv.resolved_from:
                print(f"  {'':<{W_FIELD}} {'':<10} "
                      f"{role} said {fv.reference_text.strip()[:34]!r} — value taken "
                      f"from this document's {fv.resolved_from}")

        # Phase 10. Where a side produced no value, say whether we FOUND the label
        # and distrusted the value, or never found a label at all. Those are two
        # different problems with two different fixes — one is the document's, one
        # is ours — and a reviewer cannot tell them apart from a blank cell.
        for role, fv in (("SI", c.si), ("BL", c.bl)):
            if fv is not None:
                continue
            seen = rec.labels_seen.get(role)
            if seen is None:
                continue
            if name in seen:
                note = f"{role}: label found, but the value failed verification"
            else:
                note = f"{role}: no label matching {name} was found in this document"
            print(f"  {'':<{W_FIELD}} {'':<10} {note}")

        ev = []
        if c.si is not None:
            ev.append(f"SI {c.si.source.file}:{c.si.source.locator}")
        if c.bl is not None:
            ev.append(f"BL {c.bl.source.file}:{c.bl.source.locator}")
        if ev:
            print(f"  {'':<{W_FIELD}} {'':<10} evidence: {' | '.join(ev)}")

    print()
    if rec.defects:
        print(f"  CONFIRMED DEFECTS : {', '.join(rec.defects)}")
    if rec.suspected:
        print(f"  SUSPECTED         : {', '.join(rec.suspected)}")
    if rec.unresolved:
        print(f"  UNRESOLVED        : {', '.join(rec.unresolved)}")

    from shipdoc.adapters.submission import SubmissionAdapter
    entry = SubmissionAdapter().emit([rec], expected_ids=[rec.email_id])[rec.email_id]
    print()
    print("  submission entry:")
    for k, v in entry.items():
        print(f"    {k:<15} {v}")
    print()
    _print_trace(rec)
    return 0


def _print_trace(rec) -> None:
    if not rec.trace:
        return
    print("  stage trace:")
    for ev in rec.trace:
        detail = _truncate(ev.detail, 52)
        print(f"    {ev.seq}. {ev.stage:<10} {ev.outcome:<10} {detail}")
