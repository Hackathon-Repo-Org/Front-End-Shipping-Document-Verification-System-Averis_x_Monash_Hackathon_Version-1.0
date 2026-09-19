"""M12b — the only non-deterministic component. Confined, cached, replaceable.

stdlib only: ollama speaks HTTP and `urllib` is enough. No new dependency.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol

from shipdoc.errors import LLMUnavailable
from shipdoc.infra.cache import Cache, sha256_text

DEFAULT_HOST = "http://localhost:11434"


class LLMClient(Protocol):
    def complete(self, prompt: str, *, choices: list[str] | None,
                 timeout_s: float) -> str: ...


class OllamaClient:
    """Temperature 0 and a fixed seed where supported.

    Note this is NOT a determinism guarantee: batching and GPU reduction order vary.
    I6 is claimed only for a warm cache, and the determinism test clears the cache
    between runs precisely so it cannot pass by construction.
    """

    def __init__(self, model: str, *, temperature: float = 0.0,
                 seed: int | None = 0, host: str = DEFAULT_HOST):
        self.model = model
        self.temperature = temperature
        self.seed = seed
        self.host = host.rstrip("/")

    def complete(self, prompt: str, *, choices: list[str] | None = None,
                 timeout_s: float = 30.0) -> str:
        options: dict = {"temperature": self.temperature}
        if self.seed is not None:
            options["seed"] = self.seed
        body = json.dumps({
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as r:
                payload = json.load(r)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            raise LLMUnavailable(f"ollama request failed: {e}") from e
        text = payload.get("response")
        if not isinstance(text, str):
            raise LLMUnavailable("ollama returned no 'response' field")
        return text.strip()


class CachedLLM:
    """Decorator. Cache key includes the prompt-template version, or a prompt change
    silently reuses old answers and you conclude your change did nothing.

    Caches SUCCESSES ONLY: caching a failure means a fixed bug never takes effect
    until the cache is cleared by hand.
    """

    def __init__(self, inner: LLMClient, cache: Cache, prompt_version: str):
        self.inner = inner
        self.cache = cache
        self.prompt_version = prompt_version
        self.hits = 0
        self.misses = 0

    def complete(self, prompt: str, *, choices: list[str] | None = None,
                 timeout_s: float = 30.0) -> str:
        key = sha256_text(self.prompt_version, prompt, ",".join(choices or ()))
        cached = self.cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        value = self.inner.complete(prompt, choices=choices, timeout_s=timeout_s)
        self.cache.put(key, value)
        return value


def probe(client: LLMClient, timeout_s: float = 10.0) -> bool:
    """Cheap liveness check so degraded mode is entered once, not 394 times."""
    try:
        client.complete("Reply with the single word: ok", choices=None, timeout_s=timeout_s)
        return True
    except LLMUnavailable:
        return False
