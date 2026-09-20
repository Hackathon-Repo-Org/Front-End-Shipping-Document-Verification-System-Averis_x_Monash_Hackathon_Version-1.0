"""M12d — a hosted LLM behind the existing `LLMClient` protocol.

THIS IS A SECOND IMPLEMENTATION, NOT A REWRITE. `LLMClient` is a Protocol with one
method; `classify/`, `compare/` and `state/` are untouched by this file and must stay
that way. Swapping providers is a config change, not a code change — that was the
point of confining the model behind a protocol in M12b.

ONE CLIENT, FOUR PROVIDERS
--------------------------
DeepSeek's API is OpenAI-compatible, so this is written against the OpenAI SDK with a
configurable `base_url`. The same class therefore also covers **OpenAI**, **Together**
and **Groq** by changing `llm.provider` and `llm.base_url` in `config/pipeline.yaml` —
no new code. Anything else that speaks the OpenAI chat-completions shape will work
too.

    deepseek   https://api.deepseek.com          DEEPSEEK_API_KEY
    openai     https://api.openai.com/v1         OPENAI_API_KEY
    together   https://api.together.xyz/v1       TOGETHER_API_KEY
    groq       https://api.groq.com/openai/v1    GROQ_API_KEY

WHY `deepseek-chat` AND NOT `deepseek-reasoner`
-----------------------------------------------
Every question this system asks a model is CLOSED: "return exactly one of these five
strings", or "one of these seven field names, or NONE". There is nothing to reason
about — the work is recognition, not deduction. `deepseek-reasoner` spends tokens
producing a chain of thought that is then discarded by a validator which accepts only
one exact string, so it costs more and is slower for no measurable benefit. If a
future question is genuinely open-ended, that is the moment to revisit this, not now.

OLLAMA IS NOT DEPRECATED BY THIS FILE
-------------------------------------
`llm.provider: ollama` remains fully supported and is the offline / air-gapped
option. "Runs with no network at all if a customer requires it" is a real property of
this system, and a freight operator handling commercial documents is exactly the kind
of customer who asks for it. Removing it would trade a capability for nothing.

SECRETS
-------
The key is read from the ENVIRONMENT and nowhere else. It is never written to the
cache, the run summary, a log line, an exception message or the database. `__repr__`
is overridden because the default dataclass-style repr of a client holding a key is
exactly how keys reach stack traces and issue trackers.
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from shipdoc.errors import LLMUnavailable

# provider -> (default base_url, environment variable holding the key)
PROVIDERS: dict[str, tuple[str, str]] = {
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "openai":   ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "groq":     ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
}

# Retried: rate limits and transient server faults. A 400 or a 401 is a bug or a bad
# key — retrying it just burns the batch's time and produces the same answer.
RETRY_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})

MAX_ATTEMPTS = 4
BASE_BACKOFF_S = 1.0
MAX_BACKOFF_S = 20.0


class MissingAPIKey(LLMUnavailable):
    """Raised at construction, caught by the factory, degraded to rules-only.

    A subclass of LLMUnavailable on purpose: every existing caller already handles
    that, so a missing key takes the same well-trodden degradation path as a
    dead Ollama rather than a new one nobody has tested.
    """


@dataclass
class CallMetrics:
    """A4. Per-run counters, surfaced in run_summary.

    Contains no prompt text, no response text and no key — only counts and
    milliseconds, so it is safe to serialise anywhere.
    """
    calls:        int = 0
    failures:     int = 0
    retries:      int = 0
    total_ms:     int = 0
    by_status:    dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "failures": self.failures,
            "retries": self.retries,
            "total_ms": self.total_ms,
            "mean_ms": round(self.total_ms / self.calls) if self.calls else 0,
            "retry_status_counts": dict(sorted(self.by_status.items())),
        }


def _status_of(exc: Exception) -> int | None:
    for attr in ("status_code", "http_status", "code"):
        v = getattr(exc, attr, None)
        if isinstance(v, int):
            return v
    resp = getattr(exc, "response", None)
    v = getattr(resp, "status_code", None)
    return v if isinstance(v, int) else None


class HostedClient:
    """OpenAI-compatible chat completions, one closed question at a time."""

    def __init__(self, model: str, *, provider: str = "deepseek",
                 base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, seed: int | None = 0,
                 max_attempts: int = MAX_ATTEMPTS):
        if provider not in PROVIDERS:
            raise LLMUnavailable(
                f"unknown llm.provider {provider!r}; "
                f"expected one of {sorted(PROVIDERS)} or 'ollama'")
        default_url, env_var = PROVIDERS[provider]
        key = api_key or os.environ.get(env_var, "")
        if not key.strip():
            raise MissingAPIKey(
                f"{env_var} is not set, so the {provider} provider cannot be used.\n"
                f"  Set it in your environment (see .env.example), or switch to the\n"
                f"  offline provider with  llm.provider: ollama  in "
                f"config/pipeline.yaml.\n"
                f"  Continuing without a model: classification falls back to "
                f"deterministic keyword rules.")

        self.model = model
        self.provider = provider
        self.base_url = base_url or default_url
        self.temperature = temperature
        self.seed = seed
        self.max_attempts = max_attempts
        self.metrics = CallMetrics()
        self._key = key                     # never logged, never serialised

        try:
            from openai import OpenAI
        except ImportError as e:            # pragma: no cover - env dependent
            raise LLMUnavailable(
                "the 'openai' package is required for hosted providers: "
                "pip install -e \".[hosted]\"") from e

        self._client = OpenAI(api_key=key, base_url=self.base_url,
                              max_retries=0)   # we own the retry policy

    def __repr__(self) -> str:
        """No key, ever. The default repr of an object holding a secret is how
        secrets reach stack traces, logs and bug reports."""
        return (f"HostedClient(provider={self.provider!r}, model={self.model!r}, "
                f"base_url={self.base_url!r}, api_key=<redacted>)")

    __str__ = __repr__

    def complete(self, prompt: str, *, choices: list[str] | None = None,
                 timeout_s: float = 30.0) -> str:
        """One completion. Raises LLMUnavailable after the attempt budget.

        A4: a rate limit must not kill a 520-email batch. Retries with exponential
        backoff plus jitter; when the budget is exhausted the caller sees
        LLMUnavailable, which the pipeline already turns into an escalation for that
        record rather than a crash for the run.
        """
        last: Exception | None = None
        for attempt in range(self.max_attempts):
            t0 = time.monotonic()
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    timeout=timeout_s,
                    **({"seed": self.seed} if self.seed is not None else {}),
                )
                self.metrics.calls += 1
                self.metrics.total_ms += int((time.monotonic() - t0) * 1000)
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise LLMUnavailable(f"{self.provider} returned an empty response")
                return text
            except Exception as e:  # noqa: BLE001 - classified immediately below
                self.metrics.calls += 1
                self.metrics.total_ms += int((time.monotonic() - t0) * 1000)
                status = _status_of(e)
                last = e
                if status is not None:
                    self.metrics.by_status[status] = \
                        self.metrics.by_status.get(status, 0) + 1
                retryable = status in RETRY_STATUS or status is None and _is_transport(e)
                if not retryable or attempt == self.max_attempts - 1:
                    break
                self.metrics.retries += 1
                time.sleep(_backoff(attempt))

        self.metrics.failures += 1
        raise LLMUnavailable(
            f"{self.provider} request failed after {self.max_attempts} attempt(s): "
            f"{_safe_message(last)}") from None


def _is_transport(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    return any(t in name for t in ("timeout", "connection", "apiconnection"))


def _backoff(attempt: int) -> float:
    """Exponential with full jitter. Jitter matters: 520 records hitting a rate limit
    and all sleeping exactly 2s reconverge into the same wall a second later."""
    ceiling = min(MAX_BACKOFF_S, BASE_BACKOFF_S * (2 ** attempt))
    return random.uniform(0, ceiling)


def _safe_message(exc: Exception | None) -> str:
    """The exception text with anything key-shaped removed.

    Providers sometimes echo the Authorization header back in an error body, and that
    error text goes into a StageEvent which goes into the review queue and the
    database. One redaction here covers all of them.
    """
    if exc is None:
        return "unknown error"
    import re
    msg = f"{type(exc).__name__}: {exc}"
    msg = re.sub(r"\b(sk|gsk|xai)-[A-Za-z0-9_\-]{8,}", "<redacted-key>", msg)
    msg = re.sub(r"(?i)(api[-_ ]?key|authorization|bearer)\s*[:=]\s*\S+",
                 r"\1=<redacted>", msg)
    return msg[:400]
