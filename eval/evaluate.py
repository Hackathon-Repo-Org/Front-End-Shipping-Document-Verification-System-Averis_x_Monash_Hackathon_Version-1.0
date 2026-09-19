"""Answer-key evaluator. Lives OUTSIDE src/shipdoc and is never imported by it.

STANDING RULE FOR EVERY QUERY IN THIS FILE
------------------------------------------
A query whose NAME asserts a CAUSE must assert that cause IN CODE, or be renamed to
describe only the difference it measures.

This rule exists because Phase 6's "Q1 — projection row 2 appended `suspected` and
turned a correct defect set into a wrong one" tested only `gold ⊂ ours`. It never
checked whether `suspected` was non-empty. It was not, on any of the 6 records it
named; the real cause was a label-matching bug in the .docx path. Acting on that
answer cost 5 end-to-end points before it was reverted.

Measuring a difference is cheap and safe. Naming a mechanism is a claim, and a claim
has to be checked.

THE RULE: the answer key is a MEASURING INSTRUMENT, not an input.
  - This file may read ground_truth.json.
  - No module under src/shipdoc/ may read it, import this file, or reference any
    email_id as a literal in a branch, dict key or rule.
  - tests/property/test_no_answer_key_leak.py enforces both halves.

The four scoring axes are computed by IMPORTING the organisers' own `scoring.py`.
A reimplementation that disagreed with theirs would be worse than no evaluator.

    python eval/evaluate.py [--submission output/submission.json]
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SUBMISSION = REPO / "output" / "submission.json"
DEFAULT_GT = REPO.parent / "sdoc-server" / "data_v2" / "ground_truth.json"
DEFAULT_SCORING = REPO.parent / "sdoc-server" / "server" / "scoring.py"

EDGE_CASES = [f"email_{n}" for n in range(501, 521)]


def load_scoring(path: Path):
    """Import the organisers' scoring.py by path. Never reimplement it."""
    if not path.is_file():
        raise SystemExit(f"scoring.py not found at {path}\n"
                         f"  the organiser bundle should be at ../sdoc-server/")
    spec = importlib.util.spec_from_file_location("_organiser_scoring", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_organiser_scoring"] = mod
    spec.loader.exec_module(mod)
    return mod


def classify_disagreement(ours: dict, gold: dict, comparison_category: str) -> str | None:
    o_cat, g_cat = ours.get("category"), gold.get("category")
    o_st, g_st = ours.get("status"), gold.get("status")
    o_f = set(ours.get("defect_fields") or [])
    g_f = set(gold.get("defect_fields") or [])

    if o_cat != g_cat:
        return "misclassified category"
    if g_st == "NEEDS_REVIEW" and o_st != "NEEDS_REVIEW":
        return "gold review but we committed"
    if o_st == "NEEDS_REVIEW" and g_st != "NEEDS_REVIEW":
        return "escalated but gold decided"
    if gold.get("has_defect") and not ours.get("has_defect"):
        return "missed defect"
    if ours.get("has_defect") and not gold.get("has_defect"):
        return "false defect"
    if o_f != g_f:
        return "wrong defect field set"
    if o_st != g_st:
        return "status differs"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--submission", default=str(DEFAULT_SUBMISSION))
    ap.add_argument("--ground-truth", default=str(DEFAULT_GT))
    ap.add_argument("--scoring", default=str(DEFAULT_SCORING))
    ap.add_argument("--max-lines", type=int, default=40,
                    help="cap the per-record disagreement list")
    ap.add_argument("--report", default=str(REPO / "eval" / "report.txt"),
                    help="also write the full output here")
    args = ap.parse_args()

    # Tee every line to the report file as well as stdout. A session that dies with
    # the numbers only on a terminal has lost them; this is cheap insurance.
    import builtins
    _out: list[str] = []
    _print = builtins.print       # bind the builtin BEFORE `print` becomes local

    def print(*a, **kw):          # noqa: A001 - deliberate shadow, local to main()
        _print(*a, **kw)
        _out.append(" ".join(str(x) for x in a))

    sub_path = Path(args.submission)
    if not sub_path.is_file():
        raise SystemExit(f"submission not found: {sub_path}\n"
                         f"  run  python -m shipdoc  first")
    gt_path = Path(args.ground_truth)
    if not gt_path.is_file():
        raise SystemExit(f"ground truth not found: {gt_path}")

    sub = json.loads(sub_path.read_text(encoding="utf-8"))
    truth = json.loads(gt_path.read_text(encoding="utf-8"))
    scoring = load_scoring(Path(args.scoring))

    print("=" * 78)
    print(f"EVALUATION  —  {sub_path}")
    print(f"  {len(sub)} submitted · {len(truth)} in the answer key")
    print("=" * 78)

    r = scoring.score_all(truth, sub)
    s1, s3, rel, e2e = r["stage1"], r["stage3"], r["reliability"], r["end_to_end"]
    print("\nFOUR AXES (organisers' scoring.py)")
    print(f"  stage1 macro-F1     {s1['macro_f1']:.4f}   (weight 0.30)  acc {s1['accuracy']:.4f}")
    print(f"  stage3 defect-F1    {s3['defect_f1']:.4f}   (weight 0.20)  "
          f"P {s3['defect_precision']:.3f} R {s3['defect_recall']:.3f}")
    print(f"  end-to-end          {e2e['rate']:.4f}   (weight 0.50)  "
          f"{e2e['success']}/{e2e['total']}")
    print(f"  reliability         esc-P {rel['escalation_precision']:.3f} "
          f"esc-R {rel['escalation_recall']:.3f}   (weight 0.00)")
    print(f"  FINAL SCORE         {r['final_score']:.4f}")

    # ---------------- disagreements ----------------
    kinds = collections.Counter()
    rows = []
    for eid, gold in sorted(truth.items()):
        ours = sub.get(eid, {})
        kind = classify_disagreement(ours, gold, "BL_COMPARISON")
        if kind is None:
            continue
        kinds[kind] += 1
        rows.append((eid, kind, ours, gold))

    print(f"\nDISAGREEMENTS BY TYPE  ({len(rows)} records)")
    for kind, n in kinds.most_common():
        print(f"  {n:4d}  {kind}")

    print(f"\nPER-RECORD (first {args.max_lines})")
    print(f"  {'email_id':<12} {'ours':<13} {'gold':<13} {'our fields':<28} "
          f"{'gold fields':<28} {'our reason':<18} gold reason")
    for eid, kind, ours, gold in rows[: args.max_lines]:
        print(f"  {eid:<12} {str(ours.get('status')):<13} {str(gold.get('status')):<13} "
              f"{str(ours.get('defect_fields')):<28} {str(gold.get('defect_fields')):<28} "
              f"{str(ours.get('review_reason')):<18} {gold.get('review_reason')}")
    if len(rows) > args.max_lines:
        print(f"  … {len(rows) - args.max_lines} more")

    # ---------------- planted edge cases ----------------
    print("\nPLANTED EDGE CASES (email_501–520)")
    print(f"  {'email_id':<12} {'our status':<14} {'gold status':<14} "
          f"{'our reason':<18} {'gold reason':<18} ok")
    ec_ok = 0
    for eid in EDGE_CASES:
        gold, ours = truth.get(eid, {}), sub.get(eid, {})
        same = (ours.get("status") == gold.get("status")
                and ours.get("review_reason") == gold.get("review_reason"))
        ec_ok += same
        print(f"  {eid:<12} {str(ours.get('status')):<14} {str(gold.get('status')):<14} "
              f"{str(ours.get('review_reason')):<18} {str(gold.get('review_reason')):<18} "
              f"{'yes' if same else 'NO'}")
    print(f"  {ec_ok}/{len(EDGE_CASES)} exactly right")

    # ---------------- the four questions ----------------
    print("\n" + "=" * 78)
    print("THE FOUR QUESTIONS")
    print("=" * 78)

    # Q1 — DIFFERENCE ONLY: records where the gold defect set is a strict subset of
    # ours. This says we over-report on them; it says NOTHING about why. Do not
    # rename this to blame a mechanism without asserting that mechanism here.
    q1 = []
    for eid, gold in truth.items():
        ours = sub.get(eid, {})
        if not (ours.get("status") == "MISMATCH" and gold.get("has_defect")):
            continue
        o_f, g_f = set(ours.get("defect_fields") or []), set(gold.get("defect_fields") or [])
        if o_f != g_f and g_f and g_f < o_f:
            q1.append((eid, sorted(g_f), sorted(o_f)))
    print(f"\nQ1  records where we OVER-REPORT — the gold defect set is a strict "
          f"subset of ours: {len(q1)} records")
    print("      DIFFERENCE ONLY. Cause not asserted: check rec.suspected and the "
          "extraction path before blaming the projection.")
    for eid, g, o in q1[:15]:
        print(f"      {eid}: gold {g}  ->  ours {o}")

    # Q2 — escalated-with-suspicion reported as MISMATCH: gain vs false positive
    gain = fp = 0
    for eid, gold in truth.items():
        ours = sub.get(eid, {})
        if ours.get("status") == "MISMATCH" and ours.get("review_reason") is None:
            if gold.get("has_defect"):
                gain += 1
            elif gold.get("category") == "BL_COMPARISON":
                fp += 1
    print(f"\nQ2  records we report MISMATCH: {gain} gold-defective (gain), "
          f"{fp} gold-clean (false positive)")

    # Q3 — attachment-free records we escalated that gold marks OK
    q3 = [eid for eid, gold in truth.items()
          if gold.get("status") == "OK"
          and sub.get(eid, {}).get("status") == "NEEDS_REVIEW"]
    print(f"\nQ3  records we escalated that the answer key marks OK: {len(q3)}")
    by_reason = collections.Counter(sub.get(e, {}).get("review_reason") for e in q3)
    for reason, n in by_reason.most_common():
        print(f"      {n:4d}  {reason}")

    print("\nQ4  port resolution ON vs OFF — see BACKUP/2026-09-19/phase5/NOTES.md.")
    print("      Bucket counts (measured): A=13 gains, B=3 gains, C=14 ALL HARMFUL,")
    print("      plus 18 MATCH->CANNOT_DETERMINE losses. Net 15 real detections")
    print("      destroyed. Flag stays OFF; no second scoring run spent on it.")

    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("\n".join(_out) + "\n", encoding="utf-8")
    _print(f"\nfull report written -> {rp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
