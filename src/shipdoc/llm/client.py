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

    def __init__(self, inner: LLMClient, cache: Cache, prompt_version: str,
                 model: str = ""):
        self.inner = inner
        self.cache = cache
        self.prompt_version = prompt_version
        # The MODEL is part of the key. Without it, swapping models silently reuses
        # the previous model's answers and the change appears to do nothing — the same
        # failure the prompt-version component was added to prevent.
        self.model = model or getattr(inner, "model", "")
        self.hits = 0
        self.misses = 0

    def complete(self, prompt: str, *, choices: list[str] | None = None,
                 timeout_s: float = 30.0) -> str:
        key = sha256_text(self.model, self.prompt_version, prompt,
                          ",".join(choices or ()))
        cached = self.cache.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        value = self.inner.complete(prompt, choices=choices, timeout_s=timeout_s)
        self.cache.put(key, value)
        return value


def write_manifest(cache_root, model: str, prompt_version: str) -> None:
    """Record WHICH model and prompt produced the cached answers.

    The model is already part of every cache key, so a different model simply misses
    and re-queries rather than silently reusing the wrong answers. This file is the
    human-readable counterpart: it lets someone looking at a committed cache see what
    it came from without hashing anything.
    """
    import json
    from pathlib import Path

    root = Path(cache_root)
    if not root.is_dir():
        return
    entries = sum(1 for p in root.rglob("*") if p.is_file() and p.name != "MANIFEST.json")

    # Phase 12. The cache may hold answers from SEVERAL models — the key includes the
    # model name, so they coexist without colliding. Record every model that has
    # written here, not just the last one to run, or the manifest claims a mixed
    # cache came from whichever provider happened to finish most recently.
    prior = {}
    mf = root / "MANIFEST.json"
    if mf.is_file():
        try:
            prior = json.loads(mf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prior = {}
    models = sorted({*(prior.get("models") or []),
                     *( [prior["model"]] if prior.get("model") else [] ),
                     model} - {""})

    mf.write_text(json.dumps({
        "models": models,
        "model": model,                 # the model that wrote most recently
        "prompt_version": prompt_version,
        "entries": entries,
        "note": ("Answers produced by this system's own models at temperature 0. "
                 "Keys are sha256(model + prompt_version + prompt + choices), so "
                 "entries from different models coexist and never collide — see "
                 "'models' for every provider that has written here. Values are "
                 "either one of the five category strings (the M07 classifier) or "
                 "one compared-field name / NONE / a rejected free-text reply (the "
                 "Phase 11 label proposer). No email text, no API key and no gold "
                 "labels are stored. Clear with: rm -rf cache/llm, then re-run."),
    }, indent=2) + "\n", encoding="utf-8")


def probe(client: LLMClient, timeout_s: float = 10.0) -> bool:
    """Cheap liveness check so degraded mode is entered once, not 394 times."""
    try:
        client.complete("Reply with the single word: ok", choices=None, timeout_s=timeout_s)
        return True
    except LLMUnavailable:
        return False
