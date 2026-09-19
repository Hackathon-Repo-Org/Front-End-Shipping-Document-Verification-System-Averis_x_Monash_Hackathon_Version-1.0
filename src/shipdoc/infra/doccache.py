"""M15 — content-addressed cache for extraction results.

Key = sha256(file_bytes) + extractor_name + extractor_version. Without the version
component, fixing an extractor bug has no effect until the cache is cleared by hand.

P-GATE-CACHE: what is cached here is the RAW extraction, before the quality gate.
`ExtractedDoc.ok` is the gate's verdict and the gate's input is *config*, so caching a
gated result would mean lowering `min_extract_chars` has no effect until a manual
clear — the exact bug class the spec warns about, reintroduced through a side door.
`apply_gate` therefore runs outside this cache, on the way out.
"""
from __future__ import annotations

import json

from shipdoc.infra.cache import Cache, sha256_bytes, sha256_text
from shipdoc.types import Block, ExtractedDoc, Method, SourceRef


def key_for(data: bytes, extractor_name: str, extractor_version: str) -> str:
    return sha256_text(sha256_bytes(data), extractor_name, extractor_version)


def to_json(doc: ExtractedDoc) -> str:
    return json.dumps({
        "ok": doc.ok,
        "text": doc.text,
        "method": str(doc.method),
        "detected_mime": doc.detected_mime,
        "warnings": list(doc.warnings),
        "failure": doc.failure,
        "blocks": [
            {"text": b.text, "kind": b.kind, "confidence": b.confidence,
             "file": b.ref.file, "locator": b.ref.locator,
             "span": list(b.ref.span) if b.ref.span else None}
            for b in doc.blocks
        ],
    }, ensure_ascii=False)


def from_json(raw: str) -> ExtractedDoc | None:
    """A malformed or stale entry is a miss, never a crash."""
    try:
        d = json.loads(raw)
        blocks = tuple(
            Block(text=b["text"], kind=b["kind"], confidence=b.get("confidence", 1.0),
                  ref=SourceRef(file=b["file"], locator=b["locator"],
                                span=tuple(b["span"]) if b.get("span") else None))
            for b in d["blocks"]
        )
        return ExtractedDoc(
            ok=d["ok"], text=d["text"], blocks=blocks,
            method=Method(d["method"]), detected_mime=d["detected_mime"],
            warnings=tuple(d["warnings"]), failure=d["failure"],
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def rebind(doc: ExtractedDoc, ref: str) -> ExtractedDoc:
    """Point every block's SourceRef at `ref`, leaving locators untouched."""
    if not doc.blocks or all(b.ref.file == ref for b in doc.blocks):
        return doc
    blocks = tuple(
        Block(text=b.text, kind=b.kind, confidence=b.confidence,
              ref=SourceRef(file=ref, locator=b.ref.locator, span=b.ref.span))
        for b in doc.blocks
    )
    return ExtractedDoc(ok=doc.ok, text=doc.text, blocks=blocks, method=doc.method,
                        detected_mime=doc.detected_mime, warnings=doc.warnings,
                        failure=doc.failure)


class DocCache:
    def __init__(self, cache: Cache | None):
        self.cache = cache
        self.hits = 0
        self.misses = 0

    def get(self, data: bytes, name: str, version: str,
            ref: str | None = None) -> ExtractedDoc | None:
        if self.cache is None:
            return None
        raw = self.cache.get(key_for(data, name, version))
        if raw is None:
            self.misses += 1
            return None
        doc = from_json(raw)
        if doc is None:
            self.misses += 1
            return None
        self.hits += 1
        # The key is content-addressed, so two attachments with identical bytes share
        # an entry. Rebind the evidence paths to the file actually being read, or the
        # review queue would cite whichever path happened to be extracted first.
        return rebind(doc, ref) if ref is not None else doc

    def put(self, data: bytes, name: str, version: str, doc: ExtractedDoc) -> None:
        if self.cache is None:
            return
        self.cache.put(key_for(data, name, version), to_json(doc))
