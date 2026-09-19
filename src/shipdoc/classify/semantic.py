"""M07 layer 2 — the model, on subject + body. Decides the attachment-free residue.

Constrained to the five exact strings: one retry, then None. A model that returns
"BL comparison" instead of "BL_COMPARISON" scores zero on every email it touches.
"""
from __future__ import annotations

from shipdoc.errors import LLMUnavailable
from shipdoc.types import Category, Config, Record

PROMPT_VERSION = "cls-v1"

BODY_CHARS = 1500  # signatures, legal footers and quoted threads are most of the cost

_CATEGORY_LIST = [c.value for c in Category]

TEMPLATE = """You classify emails in a shipping-documentation team inbox.

Reply with EXACTLY ONE of these labels and nothing else:
BL_COMPARISON
SI_REQUEST
INVOICE_QUERY
GENERAL
SPAM

What each label means:
- BL_COMPARISON: the sender wants a draft Bill of Lading checked or confirmed against
  a Shipping Instruction. Includes "please confirm the draft BL", "check the attached
  docs", "amend BL", and requests to verify shipment details. This applies EVEN IF no
  documents are actually attached to the email.
- SI_REQUEST: the sender is asking someone to send, submit or provide a Shipping
  Instruction, or is chasing one that is overdue.
- INVOICE_QUERY: about money — invoices, freight charges, local charges, billing,
  credit notes, payment.
- GENERAL: legitimate operational mail that is none of the above: schedules, delivery
  planning, summaries, notices, internal process updates.
- SPAM: unsolicited marketing or obvious junk.

Subject: {subject}

Body:
{body}

Label:"""


def render_prompt(record: Record) -> str:
    raw = record.raw
    return TEMPLATE.format(
        subject=(raw.get("subject") or "").strip(),
        body=(raw.get("body") or "").strip()[:BODY_CHARS],
    )


def _coerce(text: str) -> str | None:
    """Accept only the five exact labels. Never trust free text."""
    if not text:
        return None
    cleaned = text.strip().strip("`\"'*. \n\t").upper().replace(" ", "_")
    for c in _CATEGORY_LIST:
        if cleaned == c:
            return c
    # The model sometimes prefixes ("Label: X") or adds a sentence. Take a label only
    # if exactly one of the five appears as a whole token anywhere in the reply.
    hits = {c for c in _CATEGORY_LIST if c in cleaned}
    if len(hits) == 1:
        return hits.pop()
    return None


def classify_semantic(record: Record, cfg: Config, llm) -> tuple[str | None, float]:
    """Returns (category | None, confidence). Never raises LLMUnavailable — a lost
    model is degraded mode, not a crash."""
    if llm is None:
        return None, 0.0
    prompt = render_prompt(record)
    for attempt in (0, 1):                      # one retry, then give up
        try:
            reply = llm.complete(prompt, choices=_CATEGORY_LIST,
                                 timeout_s=cfg.llm.timeout_s)
        except LLMUnavailable:
            return None, 0.0
        category = _coerce(reply)
        if category is not None:
            return category, 0.9 if attempt == 0 else 0.7
    return None, 0.0
