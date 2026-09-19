"""M07 layer 2b — deterministic keyword classification, for when there is no model.

Review finding B9: degraded mode sent all 394 attachment-free emails to review, which
makes the system unusable on a laptop with no Ollama. This is the fallback that makes
`pip install -e .` enough to see the whole pipeline work.

It is rules over the subject and body ONLY. No email_id appears here, in a branch, a
dict key or a pattern — `tests/property/test_no_answer_key_leak.py` enforces that. A
rule keyed to a specific record would be memorising the answers, not classifying.

Patch 02 §5 governs the tie-breaks: lean toward the comparison category on the
margin, because misfiling a BL_COMPARISON loses that record on all three weighted
axes while a false positive costs precision on one class of one axis.
"""
from __future__ import annotations

import re

from shipdoc.types import Category

# Ordered: the first family to match wins. SPAM first because marketing copy often
# borrows shipping vocabulary; INVOICE_QUERY before the SI/BL families because a
# charges query about a shipment is still a money question.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (Category.SPAM, (
        r"\bone weird\b", r"\bincrease your\b.{0,30}\brevenue\b", r"\bclick here\b",
        r"\bunsubscribe\b", r"\blimited time offer\b", r"\bact now\b",
        r"\bguarantee[d]?\b.{0,20}\bsavings\b", r"\bwebinar\b", r"\bfree trial\b",
        r"\bcrypto\b", r"\bmiracle\b", r"\bcongratulations\b.{0,20}\bwon\b",
    )),
    (Category.INVOICE_QUERY, (
        r"\binvoice\b", r"\bcredit note\b", r"\bdebit note\b", r"\bpayment\b",
        r"\blocal charges\b", r"\btotal freight\b", r"\bfreight charges\b",
        r"\bd\s*&\s*d charges\b", r"\bdemurrage\b", r"\bdetention\b",
        r"\bbilling\b", r"\boutstanding\b.{0,20}\bamount\b", r"\bremittance\b",
        r"\bproforma\b", r"\btax\b.{0,10}\binvoice\b",
    )),
    (Category.SI_REQUEST, (
        r"\brequest\b.{0,10}\bsi\b", r"\bsi\b.{0,10}\brequest\b",
        r"\bsi needed\b", r"\bneed\b.{0,10}\bsi\b", r"\bcust si\b",
        r"\bsubmit\b.{0,15}\bsi\b", r"\bsend\b.{0,15}\bshipping instruction",
        r"\bshipping instruction\b.{0,20}\b(required|pending|outstanding|chase)\b",
        r"\bawaiting\b.{0,10}\bsi\b", r"\bpending si\b",
    )),
    (Category.BL_COMPARISON, (
        r"\bconfirm\b.{0,15}\bdocs?\b", r"\bdraft b/?l\b", r"\bbl draft\b",
        r"\bamend\b.{0,10}\bb/?l\b", r"\bcheck\b.{0,20}\b(bl|b/l|bill of lading)\b",
        r"\bverify\b.{0,20}\b(bl|b/l|documents?)\b",
        r"\bbill of lading\b.{0,20}\b(confirm|check|review|correct)\b",
        r"\bto confirm\b", r"\bplease confirm\b", r"\bconfirm the details\b",
        r"\bdocs? for (your )?(review|confirmation)\b",
    )),
)

_COMPILED = tuple(
    (cat, tuple(re.compile(p, re.IGNORECASE) for p in pats)) for cat, pats in _RULES
)

BODY_CHARS = 1500       # same window the model sees, for the same reason


def classify_rules(record, cfg) -> tuple[str | None, float]:
    """Returns (category, confidence). Never raises, never consults the network."""
    raw = record.raw
    text = f"{raw.get('subject') or ''}\n{(raw.get('body') or '')[:BODY_CHARS]}"

    hits: dict[str, int] = {}
    for cat, patterns in _COMPILED:
        n = sum(1 for p in patterns if p.search(text))
        if n:
            hits[str(cat)] = n

    if not hits:
        # No signal at all. GENERAL is the honest default for operational mail that
        # matches nothing — and it is the corpus's most common residue category.
        return str(Category.GENERAL), 0.30

    best = max(hits, key=lambda c: hits[c])

    # Patch 02 §5 tie-break: on a tie involving the comparison category, take it.
    # The error is asymmetric — a missed BL_COMPARISON is lost on all three axes.
    if str(cfg.comparison_category) in hits and \
            hits[str(cfg.comparison_category)] == hits[best]:
        best = str(cfg.comparison_category)

    # Confidence scales with how many independent patterns fired, capped below the
    # model's own first-pass confidence so the arbiter never prefers rules to a model.
    return best, min(0.35 + 0.15 * hits[best], 0.75)
