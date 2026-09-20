"""M17b — the repository interface. Phase 13 B2.

THE API WILL BE A THIN TRANSLATION LAYER. That is a decision made here, not later:
every operation the UI needs is named below, so when the HTTP service is written
there is nowhere for logic to accumulate. An endpoint that does more than convert
JSON to one of these calls and back is a bug in the design, not a feature.

The interface is deliberately NARROW. It is tempting to expose a generic query and
let the API compose whatever it wants; that is how business rules end up in
controllers, and how the SQL that actually runs in production becomes something
nobody has read.

TWO IMPLEMENTATIONS
  * `PostgresRepository` — Azure Database for PostgreSQL, the deployed target.
  * `MemoryRepository`   — SQLite (file or `:memory:`), so the test suite and the
                           clean-clone gate run with NO database at all.

The second is not a toy. Gate 2 requires that a fresh clone with no `DATABASE_URL`
reproduces the committed submission hash, and a test suite that needs a server is a
test suite that gets skipped.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class RecordFilter:
    """What the UI's record list can filter on, and nothing else.

    Every field here maps to an index declared in models.py. A filter with no index
    behind it is a table scan that only shows up under load.
    """
    run_id:   uuid.UUID | None = None
    status:   str | None = None          # OK | MISMATCH | NEEDS_REVIEW
    category: str | None = None
    email_id: str | None = None
    has_defect: bool | None = None
    # Phase 14, for the reviewer UI.
    review_reason: str | None = None
    # None means EXCLUDE awaiting-documents records. Not a neutral default: those
    # ~90 records are a shipper saying "the draft is coming", they are OK rather
    # than work, and mixing them into the queue buries the genuinely broken ones.
    awaiting_documents: bool | None = None
    decided:  bool | None = None         # has an active human decision
    q:        str | None = None          # free text over id, party names, ports
    limit:    int = 100
    offset:   int = 0


@dataclass
class RunInput:
    """Everything needed to record one run. R4: it must be able to say what
    produced it, so these hashes are required rather than optional."""
    code_version:          str
    config_sha256:         str
    submission:            dict
    submission_sha256:     str
    records:               list
    learned_labels_sha256: str = ""
    decisions_sha256:      str = ""
    llm_provider:          str | None = None
    llm_model:             str | None = None
    prompt_version:        str | None = None
    degraded:              bool = False
    run_summary_sha256:    str | None = None
    llm_calls:             list = dc_field(default_factory=list)
    run_id:                uuid.UUID | None = None


@runtime_checkable
class Repository(Protocol):
    """The whole surface. If the API needs something not here, add it HERE first."""

    # ---- writing a run (R2: this only ever INSERTs; nothing is updated) ----
    def save_run(self, run: RunInput) -> uuid.UUID: ...

    # ---- reading, for the UI ----
    def list_records(self, filters: RecordFilter) -> list[dict]: ...
    def get_record_detail(self, email_id: str,
                          run_id: uuid.UUID | None = None) -> dict | None: ...
    def latest_evaluation(self) -> dict | None: ...

    # ---- the human in the loop ----
    def record_decision(self, email_id: str, field: str | None, decision_type: str,
                        reviewer: str, **kw) -> int: ...
    def list_decisions(self, email_id: str | None = None) -> list[dict]: ...

    def list_proposals(self, status: str = "pending") -> list[dict]: ...
    def decide_proposal(self, proposal_id: int, status: str,
                        decided_by: str, note: str = "") -> None: ...

    # ---- scores only (R5). There is no method to store gold labels. ----
    def save_evaluation(self, run_id: uuid.UUID, scores: dict) -> None: ...


def utcnow() -> datetime:
    """UTC, always. A naive timestamp from one region and one from another are
    silently hours apart, and it surfaces as an out-of-order audit trail."""
    return datetime.now(timezone.utc)


def database_url() -> str | None:
    """From the environment ONLY. Never config, never a file in the repo.

    Returns None when unset, which is the signal to run without a database — the
    supported default, not a degraded mode.
    """
    import os
    url = (os.environ.get("DATABASE_URL") or "").strip()
    return url or None


def build_repository(url: str | None = None) -> "Repository | None":
    """The factory. `None` means "no database configured", and every caller must
    treat that as normal rather than as an error.

    Gate 2 is exactly this returning None and the run proceeding unchanged.
    """
    url = url if url is not None else database_url()
    if not url:
        return None
    if url.startswith("sqlite"):
        from shipdoc.adapters.db.sqlstore import SQLRepository
        return SQLRepository(url)
    from shipdoc.adapters.db.sqlstore import SQLRepository
    return SQLRepository(url)
