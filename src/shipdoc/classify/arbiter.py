"""M07 layer 3 — combine structural and semantic evidence.

Structural evidence outranks text evidence when they conflict: the brief warns that
subject lines may be misleading, and an attachment pair is a fact about the email.

Patch 02 §5 — lean toward the comparison category on the margin, because the error
is asymmetric. Calling something BL_COMPARISON wrongly costs precision on one class
of a macro-F1 worth 0.30. Calling a BL_COMPARISON something else loses that record on
0.30 + 0.20 + 0.50, because both comparison axes gate on the PREDICTED category
(scoring.py:81 and :157).
"""
from __future__ import annotations

from shipdoc.classify.semantic import classify_semantic
from shipdoc.classify.structural import classify_structural
from shipdoc.types import Config, Record


def classify(record: Record, cfg: Config, llm) -> tuple[str | None, float]:
    """M07's interface. `None` means the arbiter could not decide, which `evaluate`
    turns into an escalation — v1.0's `tuple[str, float]` had no channel for this.
    """
    structural = classify_structural(record, cfg)

    # Structural made a positive identification (an SI/BL pair, or half of one).
    if structural.category is not None:
        if cfg.flags.structural_decisive:
            return structural.category, structural.confidence

        # Policy B: the model may overturn the structural signal. Patch 02 §5 warns
        # against letting it do so lightly, so it must produce a definite competing
        # label; an undecided model leaves the structural verdict standing.
        semantic, conf = classify_semantic(record, cfg, llm)
        if semantic is None or semantic == structural.category:
            return structural.category, structural.confidence
        return semantic, min(conf, 0.6)

    # Phase 10 Fix 3 — a deterministic body-intent rule, AHEAD of the model.
    #
    # Placed after the structural check and before the semantic one, on purpose. An
    # attachment pair is a fact about the email and keeps its precedence; the model
    # is a guess informed by the whole text, including a subject line that may
    # describe a different matter in the same thread. An explicit written instruction
    # to compare a BL against an SI sits between the two: weaker than a fact, stronger
    # than an inference.
    #
    # It can only ever ADD records to the comparison category, never remove them, so
    # its risk is one-directional and was measured as such.
    from shipdoc.classify.intent import requests_bl_comparison

    if requests_bl_comparison(record):
        return cfg.comparison_category, 0.9

    # No structural view: this is the attachment-free residue, ~76% of the corpus.
    semantic, conf = classify_semantic(record, cfg, llm)
    if semantic is not None:
        return semantic, conf

    # The model is absent or could not decide. Fall back to deterministic keyword
    # rules rather than escalating (review finding B9): sending all 394 of these to
    # review makes the system unusable on a machine with no Ollama, and a rules-only
    # answer is both honest and far better than no answer. `run_summary.degraded`
    # records that this happened.
    from shipdoc.classify.rules import classify_rules
    return classify_rules(record, cfg)
