"""M13b — the pending label-proposal queue.

    AI PROPOSES  ·  A HUMAN APPROVES  ·  RULES EXECUTE

This file owns the middle word. A proposal sits here, inert, until a person acts on
it. Nothing in this module can approve anything, and there is deliberately no code
path that writes an entry straight into the learned vocabulary — approval goes
through `cli`, driven by a human, and records who they were.

A proposal with no evidence line is not reviewable, so `write_proposals` refuses to
emit one. Asking someone to rule on `Containers:` with no document, no line number
and no surrounding text is asking them to guess, and a queue that trains its reviewer
to guess is worse than no queue.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

NONE = "NONE"          # the model's "this names no compared field"

STATUS_PENDING = "pending"


@dataclass(frozen=True)
class Proposal:
    """One question for one human about one label.

    `normalised` is the identity. One label, one proposal, once ever — across the
    whole corpus and across runs.
    """
    normalised:     str
    label:          str
    proposed_field: str          # a field name, or NONE
    model:          str
    prompt_version: str
    doc_ref:        str
    line_no:        int
    role:           str
    value:          str
    context:        str
    occurrences:    int = 1
    status:         str = STATUS_PENDING

    def is_reviewable(self) -> bool:
        """Evidence a person can actually judge: where it came from and what it said."""
        return bool(self.doc_ref and self.line_no > 0 and self.context.strip()
                    and self.label.strip())


def read_proposals(path: Path) -> list[Proposal]:
    path = Path(path)
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = raw.get("proposals") if isinstance(raw, dict) else raw
    out = []
    for r in rows or []:
        try:
            out.append(Proposal(**{k: v for k, v in r.items()
                                   if k in Proposal.__dataclass_fields__}))
        except TypeError:
            continue
    return out


def write_proposals(path: Path, proposals: list[Proposal]) -> int:
    """Write the pending queue. Returns how many were written.

    Unreviewable proposals are dropped here rather than at the call site, so there is
    exactly one place the rule can be weakened.
    """
    keep = [p for p in proposals if p.is_reviewable()]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "note": ("Proposed label->field mappings awaiting human approval. Nothing "
                 "here has taken effect. Review with: python -m shipdoc labels list"),
        "proposals": [asdict(p) for p in sorted(keep, key=lambda p: p.normalised)],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return len(keep)


def already_known(normalised: str, vocab, pending: list[Proposal]) -> bool:
    """Once ever. Approved, rejected, or already queued — do not ask again.

    Rejections are included on purpose: a reviewer who says no to a label and is
    asked the same question next week has been told their answer did not matter.
    """
    if any(e.normalised == normalised for e in getattr(vocab, "entries", ())):
        return True
    return any(p.normalised == normalised for p in pending)
