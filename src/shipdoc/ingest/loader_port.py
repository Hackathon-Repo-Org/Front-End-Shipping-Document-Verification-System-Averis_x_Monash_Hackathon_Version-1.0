"""M04 — thin adapter over the supplied `loader.py`.

Isolates the pipeline from it: no `loader.Inbox` type may appear in a hint anywhere
else, or unit tests need the dataset.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Iterator, Protocol

from shipdoc.errors import IngestError

_RETRIES = 3
_BACKOFF_S = 0.5


class InboxPort(Protocol):
    def emails(self) -> Iterator[dict]: ...
    def read_bytes(self, path: str) -> bytes: ...
    def submit(self, payload: dict) -> dict: ...


def _load_provided_loader(bundle_root: Path):
    """Import the bundle's `loader.py` by path, without putting it on sys.path."""
    mod = sys.modules.get("_shipdoc_provided_loader")
    if mod is not None:
        return mod
    target = bundle_root / "loader.py"
    if not target.is_file():
        raise IngestError(f"provided loader.py not found at {target}")
    spec = importlib.util.spec_from_file_location("_shipdoc_provided_loader", target)
    if spec is None or spec.loader is None:
        raise IngestError(f"could not load {target}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_shipdoc_provided_loader"] = mod
    spec.loader.exec_module(mod)
    return mod


class LoaderInbox:
    """`source` is a local bundle directory or an `http(s)://` server URL."""

    def __init__(self, source: str, bundle_root: str | Path | None = None):
        self.source = str(source).rstrip("/")
        self.is_http = self.source.startswith(("http://", "https://"))
        root = Path(bundle_root) if bundle_root else (
            Path(__file__).resolve().parents[3] / "dataset" if self.is_http
            else Path(self.source))
        loader = _load_provided_loader(Path(root))
        self._inbox = loader.Inbox(self.source)
        self._count: int | None = None

    # -- listing ---------------------------------------------------------

    def emails(self) -> list[dict]:
        """Sorted by email_id: `emails()` ordering is not guaranteed stable, and two
        runs with differently-ordered logs are painful to diff.

        A network source can fail mid-iteration, so the fetch is retried whole and the
        final count asserted — a partial iteration must never pass as a complete corpus.
        """
        records = self._fetch()
        ids = [r["email_id"] for r in records]
        if len(set(ids)) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise IngestError(f"duplicate email_id values in corpus: {dupes}")
        if self._count is not None and len(records) != self._count:
            raise IngestError(
                f"corpus size changed between reads: {self._count} -> {len(records)}")
        self._count = len(records)
        return sorted(records, key=lambda r: r["email_id"])

    def _fetch(self) -> list[dict]:
        attempts = _RETRIES if self.is_http else 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                records = list(self._inbox.emails())
            except Exception as e:  # network, disk, malformed JSON
                last = e
                if attempt + 1 < attempts:
                    time.sleep(_BACKOFF_S * (2 ** attempt))
                continue
            if not records:
                raise IngestError(f"no email records found at {self.source}")
            return [dict(r) for r in records]
        raise IngestError(f"could not read corpus from {self.source}: {last}") from last

    def get(self, email_id: str) -> dict:
        try:
            return dict(self._inbox.get(email_id))
        except Exception as e:
            raise IngestError(f"could not read {email_id}: {e}") from e

    # -- attachments -----------------------------------------------------

    def read_bytes(self, path: str) -> bytes:
        """Always bytes. Never `read_text()`: the provided loader decodes with
        errors='replace', so a .pdf/.docx/.xlsx becomes silent mojibake rather than
        raising. Decoding belongs to the extractor, which knows the format.
        """
        try:
            data = self._inbox.read_bytes(path)
        except Exception as e:
            raise IngestError(f"could not read attachment {path}: {e}") from e
        if not isinstance(data, (bytes, bytearray)):
            raise IngestError(f"attachment {path} did not read as bytes")
        return bytes(data)

    # -- submission ------------------------------------------------------

    def submit(self, payload: dict) -> dict:
        if not self.is_http:
            raise IngestError(
                "cannot submit: no scoreboard server URL is configured. "
                "The static bundle is data-only; the /submit endpoint lives on the "
                "Docker option. Re-run with --server-url http://<host>:8080 once the "
                "server bundle is available."
            )
        last: Exception | None = None
        for attempt in range(_RETRIES):
            try:
                return self._inbox.submit(payload)
            except Exception as e:
                last = e
                if attempt + 1 < _RETRIES:
                    time.sleep(_BACKOFF_S * (2 ** attempt))
        raise IngestError(f"submission to {self.source} failed: {last}") from last
