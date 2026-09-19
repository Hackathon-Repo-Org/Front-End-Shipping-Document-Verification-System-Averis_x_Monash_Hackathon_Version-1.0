"""M15 — content-addressed cache with atomic writes.

Cache writes are atomic (temp + rename): a killed process must not leave a
half-written entry that deserialises into garbage on the next run.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def sha256_text(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Cache:
    """Flat content-addressed store. Keys are hex digests; values are text."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        # shard by the first two hex chars so one directory does not grow unbounded
        return self.root / key[:2] / key

    def get(self, key: str) -> str | None:
        p = self._path(key)
        try:
            return p.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return None

    def put(self, key: str, value: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(value)
            os.replace(tmp, p)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


class NullCache(Cache):
    """For tests that must exercise a cold path every time."""

    def __init__(self):
        super().__init__(Path("."))

    def get(self, key: str) -> str | None:
        return None

    def put(self, key: str, value: str) -> None:
        return None
