"""M12c — ask the model ONE question about ONE unknown label.

    AI PROPOSES  ·  A HUMAN APPROVES  ·  RULES EXECUTE

This is the "proposes" end, and it is the only place a model is allowed anywhere near
the label vocabulary. Its output is a SUGGESTION written to a queue. It never reaches
`config/learned_labels.yaml` without a person, and this module has no code that could
put it there.

The question is closed, exactly as M07's classifier question is: the answer must be
one of the seven compared field names or the literal string NONE. Free text is not
accepted — not parsed leniently, not fuzzy-matched, not "close enough". One retry,
then NONE, which queues nothing.

AUTO-REJECT BEFORE ASKING
-------------------------
A label already listed as an anti_synonym is refused without a model call. `NET
WEIGHT` must never reach a reviewer as a candidate for gross_weight_kg: the config
already encodes that this is forbidden, and spending a person's attention on a
question the system can answer itself is how a review queue loses its reader. It also
saves a model call, but that is not the reason.
"""
from __future__ import annotations

from shipdoc.errors import LLMUnavailable
from shipdoc.review.proposals import NONE, Proposal
from shipdoc.types import Config, UnknownLabel

PROMPT_VERSION = "labels-v1"

_PROMPT = """You are reading a line from a shipping document (a Shipping Instruction \
or a Bill of Lading).

A line carries the label below, followed by a value:

  label: {label}
  value: {value}

Surrounding lines for context:
---
{context}
---

Which ONE of these compared fields does this label name?

{choices}
  NONE

Rules:
- Answer with exactly one item from the list above, copied exactly.
- Answer NONE if the label names none of them, or if you are unsure.
- NONE is the correct answer for container numbers, seal numbers, vessel names,
  voyage numbers, dates, references, marks and numbers, and commodity descriptions.
- Do not explain. Output only the one word or phrase."""


def _auto_rejected(label_norm: str, cfg: Config) -> str | None:
    """Return the field whose anti_synonym list already forbids this label."""
    from shipdoc.learned import normalise_label

    for fname, spec in cfg.fields.items():
        for anti in spec.anti_synonyms:
            if normalise_label(anti) == label_norm:
                return fname
    return None


def propose(unknown: UnknownLabel, cfg: Config, llm) -> Proposal | None:
    """One label in, at most one Proposal out. None means do not queue anything.

    Returns None when the label is auto-rejected, when there is no model, or when the
    model declines with NONE. A NONE answer is deliberately NOT queued: asking a human
    to confirm that `Vessel:` is not one of our seven fields wastes the one resource
    this whole design is trying to spend carefully.
    """
    if _auto_rejected(unknown.normalised, cfg) is not None:
        return None
    if llm is None:
        return None

    choices = list(cfg.fields)
    prompt = _PROMPT.format(
        label=unknown.raw,
        value=unknown.value[:120],
        context=unknown.context[:600],
        choices="\n".join(f"  {c}" for c in choices),
    )

    answer = _ask(llm, prompt, choices)
    if answer is None or answer == NONE:
        return None

    return Proposal(
        normalised=unknown.normalised,
        label=unknown.raw,
        proposed_field=answer,
        model=getattr(llm, "model", "") or getattr(getattr(llm, "inner", None), "model", ""),
        prompt_version=PROMPT_VERSION,
        doc_ref=unknown.doc_ref,
        line_no=unknown.line_no,
        role=unknown.role,
        value=unknown.value[:200],
        context=unknown.context[:800],
    )


def _ask(llm, prompt: str, choices: list[str]) -> str | None:
    """Closed vocabulary, one retry, then give up. Never accept free text."""
    allowed = set(choices) | {NONE}
    for attempt in range(2):
        try:
            raw = llm.complete(prompt, choices=choices + [NONE], timeout_s=30.0)
        except LLMUnavailable:
            return None
        text = (raw or "").strip().strip(".`\"'").strip()
        if text in allowed:
            return text
        # Exactly one forgiving step: case. Anything beyond that is the model
        # answering a different question than the one it was asked.
        lowered = {c.lower(): c for c in allowed}
        if text.lower() in lowered:
            return lowered[text.lower()]
        if attempt == 0:
            prompt = (prompt + "\n\nYour previous answer was not one of the allowed "
                               "options. Reply with exactly one of them, or NONE.")
    return None
