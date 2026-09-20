"""M16b — the APPROVES step, driven by a human at a terminal.

    AI PROPOSES  ·  A HUMAN APPROVES  ·  RULES EXECUTE

This is a CLI because a CLI is what exists today; the same three operations are one
card on the review screen when there is a UI. Nothing about the design assumes a
terminal — `list`, `approve` and `reject` are the whole interface.

There is deliberately NO `--all`, no `--auto`, and no confidence threshold above which
something approves itself. A proposal that applies itself is precisely the failure
this design exists to prevent, and the convenience flag is how it would arrive.

Rejections are written down as permanently as approvals. A reviewer who says no and
is asked the same question next week has been told their answer did not matter, and
shortly afterwards they stop reading the queue.
"""
from __future__ import annotations

import datetime as _dt
import getpass
from pathlib import Path

from shipdoc.learned import FILENAME, normalise_label
from shipdoc.review.proposals import read_proposals, write_proposals

_HEADER = "  {:<26} {:<20} {:<7} {}"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _who(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        return getpass.getuser() or "unknown"
    except Exception:
        return "unknown"


def cmd_list(queue_path: Path) -> int:
    proposals = read_proposals(queue_path)
    if not proposals:
        print(f"No pending label proposals. ({queue_path})")
        print("  A run writes them when it meets a label-shaped line it does not know.")
        return 0

    print(f"{len(proposals)} proposal(s) awaiting approval — {queue_path}")
    print("  NOTHING BELOW HAS TAKEN EFFECT.\n")
    print(_HEADER.format("label", "proposed field", "role", "evidence"))
    print("  " + "-" * 76)
    for p in proposals:
        print(_HEADER.format(p.label[:26], p.proposed_field[:20], p.role,
                             f"{p.doc_ref}:line {p.line_no}"))
        print(f"      value seen: {p.value[:60]!r}")
        print(f"      proposed by {p.model or 'unknown model'} "
              f"({p.prompt_version})")
        for line in p.context.splitlines()[:4]:
            print(f"      | {line[:70]}")
        print()
    print("  Approve:  python -m shipdoc labels approve \"<label>\"")
    print("  Reject :  python -m shipdoc labels reject  \"<label>\"")
    return 0


def _decide(queue_path: Path, config_dir: Path, label: str, decision: str,
            who: str | None, note: str) -> int:
    key = normalise_label(label)
    proposals = read_proposals(queue_path)
    match = next((p for p in proposals if p.normalised == key), None)
    if match is None:
        print(f"shipdoc: no pending proposal for {label!r}")
        print("  see:  python -m shipdoc labels list")
        return 2

    entry = {
        "label": match.label,
        "normalised": match.normalised,
        "field": match.proposed_field,
        "decision": decision,
        "approved_by": _who(who),
        "approved_at": _now(),
        "model": match.model or "unknown",
        "prompt_version": match.prompt_version,
    }
    if note:
        entry["note"] = note

    _append_entry(Path(config_dir) / FILENAME, entry)

    remaining = [p for p in proposals if p.normalised != key]
    write_proposals(queue_path, remaining)

    verb = "APPROVED" if decision == "approve" else "REJECTED"
    print(f"{verb}: {match.label!r} -> {match.proposed_field}")
    print(f"  written to {Path(config_dir) / FILENAME}")
    print(f"  by {entry['approved_by']} at {entry['approved_at']}")
    if decision == "approve":
        print("  It is a deterministic rule from the next run onward.")
    else:
        print("  Recorded as an anti-synonym. You will not be asked again.")
    return 0


def _append_entry(path: Path, entry: dict) -> None:
    """Record one decision. At most ONE active entry per label, ever.

    A second ruling on the same label SUPERSEDES the first rather than sitting
    beside it. Two active records for one label means the file no longer says who
    is accountable for that rule — and the whole point of the provenance fields is
    that exactly one person is.

    This is how a decision made by the wrong party gets corrected: re-approve under
    your own name and the earlier attribution is replaced, not accumulated.

    Nothing is destroyed. The superseded entry moves to a `superseded:` list in the
    same file, which the loader ignores and an auditor can read. That is HARD RULE 1
    applied to a decision record: the history of who decided what is exactly the kind
    of thing that must not quietly vanish.
    """
    import yaml

    doc = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            doc = loaded

    key = entry["normalised"]
    labels = list(doc.get("labels") or [])
    retired = [e for e in labels
               if str(e.get("normalised") or normalise_label(str(e.get("label", ""))))
               == key]
    labels = [e for e in labels if e not in retired]
    labels.append(entry)
    doc["labels"] = labels

    if retired:
        history = list(doc.get("superseded") or [])
        history.extend(retired)
        doc["superseded"] = history

    header = (
        "# Learned label vocabulary — APPROVED BY A HUMAN, one entry at a time.\n"
        "#\n"
        "# Written by `python -m shipdoc labels approve|reject`. Safe to read, edit\n"
        "# and revert by hand; it is loaded ALONGSIDE fields.yaml and never merged\n"
        "# into it, so deleting this file returns the system to hand-written rules.\n"
        "#\n"
        "# Only label->field mappings live here. A rule saying two VALUES mean the\n"
        "# same thing is refused at load time — see src/shipdoc/learned.py.\n"
        "#\n"
        "# This file's sha256 is recorded in output/run_summary.json, because\n"
        "# reproducibility is only meaningful against a stated vocabulary.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def run(action: str, label: str | None, *, out_dir: str, config_dir: str,
        who: str | None = None, note: str = "") -> int:
    queue_path = Path(out_dir) / "label_proposals.json"
    if action == "list":
        return cmd_list(queue_path)
    if action in ("approve", "reject"):
        if not label:
            print(f"shipdoc: labels {action} needs the label, e.g.\n"
                  f'  python -m shipdoc labels {action} "Containers:"')
            return 2
        return _decide(queue_path, Path(config_dir), label, action, who, note)
    print(f"shipdoc: unknown labels action {action!r}; use list, approve or reject")
    return 2
