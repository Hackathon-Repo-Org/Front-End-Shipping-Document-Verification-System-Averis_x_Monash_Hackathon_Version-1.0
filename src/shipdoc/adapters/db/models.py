"""M17 — the database schema. Phase 13.

    THE DATABASE IS AN ADAPTER (rule R1).

It lives here, at the top layer, and nothing under `ingest/`, `detect/`, `extract/`,
`route/`, `normalise/`, `compare/`, `state/` or `classify/` may import it.
`tests/property/test_layering.py` enforces that the same way it enforces every other
edge, and `tests/property/test_db_is_optional.py` proves a run with no DATABASE_URL
is byte-identical to one without the package installed at all.

The five rules, and where each one is visible in this file:

  R1  ADAPTER              this module imports no core module except `types`
  R2  RUNS ARE IMMUTABLE   no row here is updated after a run completes;
                           re-processing inserts a new `run_id`. There is no
                           `updated_at` column anywhere, on purpose.
  R3  DECISIONS OUTLIVE    `review_decisions` is keyed on (email_id, field) and
      RUNS                 carries NO run_id. They are applied at projection time,
                           so every future run inherits them.
  R4  REPRODUCIBILITY      `runs` records config_sha256, learned_labels_sha256,
                           decisions_sha256, code_version, provider, model and
                           prompt_version. A run that cannot say what produced it
                           is a number nobody can defend.
  R5  NO GOLD LABELS       there is NO table for the answer key, and there will not
                           be one. `evaluations` holds SCORES only. The key stays
                           outside the repo and outside the database;
                           `eval/evaluate.py` reads it and writes only the numbers.

Two type choices that are not negotiable:

  * Weights and scores are NUMERIC, never FLOAT. Binary floating point cannot
    represent 0.1, and a scoreboard that disagrees with itself in the fourth decimal
    place between two runs is a scoreboard nobody trusts.
  * Timestamps are TIMESTAMPTZ and written in UTC. A naive timestamp from a server
    in Kuala Lumpur and one from a container in West Europe are silently eight hours
    apart, and the bug surfaces as an out-of-order audit trail months later.

Attachment BYTES are not stored here. They live in Azure Blob Storage; this schema
holds the metadata and the blob URL. A 520-document corpus fits in a database, but
the next one will not, and a blob column is the hardest thing to migrate out of later.
"""
from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator, CHAR

# Explicit naming convention so Alembic autogenerate produces stable, reviewable
# migration names instead of database-assigned ones that differ per environment.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class JSONBType(TypeDecorator):
    """JSONB on PostgreSQL, JSON everywhere else.

    The fallback is what lets the whole test suite and the clean-clone gate run on
    SQLite with no database server. Azure SQL would take NVARCHAR(MAX) plus the JSON
    functions — noted in HANDOVER.
    """
    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class GUID(TypeDecorator):
    """UUID on PostgreSQL, CHAR(36) elsewhere. Same reason as JSONBType."""
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        return None if value is None else uuid.UUID(str(value))


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _sha() -> Mapped[str]:
    return mapped_column(CHAR(64), nullable=False)


# BIGSERIAL on PostgreSQL, INTEGER on SQLite.
#
# SQLite only auto-increments a column declared exactly `INTEGER PRIMARY KEY`; a
# BIGINT primary key is NOT NULL with no default, so every insert fails. The variant
# keeps the production type honest while letting the whole suite and the clean-clone
# gate run with no database server.
BigPK = BigInteger().with_variant(Integer, "sqlite")


# ------------------------------------------------------------------- INPUT

class Email(Base):
    """`email_id` is the NATURAL key from the corpus and the primary key.

    No surrogate id. The organisers' submission format is keyed by `email_id`, so a
    surrogate would add a join to every query and a translation step to the one
    artifact that must be exactly right.
    """
    __tablename__ = "emails"

    email_id:    Mapped[str] = mapped_column(Text, primary_key=True)
    subject:     Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    body:        Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    received_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    source:      Mapped[str] = mapped_column(Text, nullable=False,
                                             server_default="corpus")
    ingested_at: Mapped[object] = mapped_column(DateTime(timezone=True),
                                                nullable=False,
                                                server_default=func.now())

    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="email", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("source in ('corpus','upload')", name="source_vocab"),
    )


class Attachment(Base):
    """Metadata and a blob URL. The BYTES live in Azure Blob Storage."""
    __tablename__ = "attachments"

    attachment_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    email_id:      Mapped[str] = mapped_column(
        Text, ForeignKey("emails.email_id", ondelete="CASCADE"), nullable=False)
    filename:      Mapped[str] = mapped_column(Text, nullable=False)
    content_type:  Mapped[str | None] = mapped_column(Text)
    size_bytes:    Mapped[int | None] = mapped_column(BigInteger)
    sha256:        Mapped[str] = _sha()
    blob_url:      Mapped[str | None] = mapped_column(Text)
    detected_type: Mapped[str | None] = mapped_column(Text)   # SI | BL | UNKNOWN

    email: Mapped[Email] = relationship(back_populates="attachments")

    __table_args__ = (
        UniqueConstraint("email_id", "filename", name="uq_attachment_email_filename"),
    )


# ----------------------------------------------------------------- PROCESS

class Run(Base):
    """R2 + R4. Immutable once complete, and able to say what produced it.

    Every hash here answers a question someone WILL ask three weeks later: "why did
    the score change?" Without `learned_labels_sha256` the answer to that question
    after Phase 11 is a shrug.
    """
    __tablename__ = "runs"

    run_id:      Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True,
                                                   default=uuid.uuid4)
    started_at:  Mapped[object] = mapped_column(DateTime(timezone=True),
                                                nullable=False,
                                                server_default=func.now())
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status:      Mapped[str] = mapped_column(Text, nullable=False)

    code_version:          Mapped[str] = mapped_column(Text, nullable=False)
    config_sha256:         Mapped[str] = _sha()
    learned_labels_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False,
                                                       server_default="")
    decisions_sha256:      Mapped[str] = mapped_column(CHAR(64), nullable=False,
                                                       server_default="")

    llm_provider:   Mapped[str | None] = mapped_column(Text)
    llm_model:      Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)

    degraded:     Mapped[bool] = mapped_column(Boolean, nullable=False,
                                               server_default="false")
    record_count: Mapped[int | None] = mapped_column(Integer)

    submission_sha256:  Mapped[str | None] = mapped_column(CHAR(64))
    run_summary_sha256: Mapped[str | None] = mapped_column(CHAR(64))

    records: Mapped[list["DBRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status in ('running','complete','failed')",
                        name="status_vocab"),
    )


class DBRecord(Base):
    """One email's outcome in one run.

    `decided_by` ('rule' | 'llm') is not bookkeeping — the dashboard reports the AI's
    share of decisions from it, and it is a rubric item.

    `reason_key` holds the INTERNAL vocabulary (`err_no_value`), not the external
    `review_reason` spelling. Conflating them here would undo the boundary that
    `adapters/reason_map.py` exists to maintain; `review_reason` is stored beside it
    as the external value, and the two are deliberately different columns.
    """
    __tablename__ = "records"

    record_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    run_id:    Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    email_id:  Mapped[str] = mapped_column(
        Text, ForeignKey("emails.email_id"), nullable=False)

    category:      Mapped[str | None] = mapped_column(Text)
    decided_by:    Mapped[str | None] = mapped_column(Text)
    state:         Mapped[str] = mapped_column(Text, nullable=False)
    reason_key:    Mapped[str | None] = mapped_column(Text)
    status:        Mapped[str] = mapped_column(Text, nullable=False)
    review_reason: Mapped[str | None] = mapped_column(Text)

    has_defect: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                             server_default="false")
    awaiting_documents: Mapped[bool] = mapped_column(Boolean, nullable=False,
                                                     server_default="false")

    run: Mapped[Run] = relationship(back_populates="records")
    comparisons: Mapped[list["DBComparison"]] = relationship(
        back_populates="record", cascade="all, delete-orphan")
    events: Mapped[list["StageEventRow"]] = relationship(
        back_populates="record", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("run_id", "email_id", name="uq_records_run_email"),
        CheckConstraint("state in ('resolved','escalated','failed')",
                        name="state_vocab"),
        CheckConstraint("status in ('OK','MISMATCH','NEEDS_REVIEW')",
                        name="status_vocab"),
        CheckConstraint("decided_by is null or decided_by in ('rule','llm')",
                        name="decided_by_vocab"),
        Index("ix_records_run_status", "run_id", "status"),
        Index("ix_records_run_category", "run_id", "category"),
        Index("ix_records_email", "email_id"),
    )


class DBComparison(Base):
    """One field, one verdict, with the evidence a reviewer needs.

    `si_numeric`/`bl_numeric` are NUMERIC. A gross weight compared as a float is a
    gross weight that disagrees with itself.
    """
    __tablename__ = "comparisons"

    comparison_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("records.record_id", ondelete="CASCADE"),
        nullable=False)

    field:      Mapped[str] = mapped_column(Text, nullable=False)
    verdict:    Mapped[str] = mapped_column(Text, nullable=False)
    leaning:    Mapped[str | None] = mapped_column(Text)
    si_value:   Mapped[str | None] = mapped_column(Text)
    bl_value:   Mapped[str | None] = mapped_column(Text)
    si_numeric: Mapped[object | None] = mapped_column(Numeric)
    bl_numeric: Mapped[object | None] = mapped_column(Numeric)
    si_evidence: Mapped[dict | None] = mapped_column(JSONBType)
    bl_evidence: Mapped[dict | None] = mapped_column(JSONBType)
    strategy:   Mapped[str | None] = mapped_column(Text)
    detail:     Mapped[str | None] = mapped_column(Text)

    record: Mapped[DBRecord] = relationship(back_populates="comparisons")

    __table_args__ = (
        UniqueConstraint("record_id", "field", name="uq_comparisons_record_field"),
        CheckConstraint("verdict in ('MATCH','MISMATCH','CANNOT_DETERMINE')",
                        name="verdict_vocab"),
        Index("ix_comparisons_record", "record_id"),
    )


class StageEventRow(Base):
    """`seq` is monotonic and there is NO wall-clock column.

    A timestamp here would break I6: two runs over the same input would differ in
    every event row, and "the output is byte-identical" would stop being checkable.
    """
    __tablename__ = "stage_events"

    event_id:  Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("records.record_id", ondelete="CASCADE"),
        nullable=False)
    seq:     Mapped[int] = mapped_column(Integer, nullable=False)
    stage:   Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    detail:  Mapped[str | None] = mapped_column(Text)

    record: Mapped[DBRecord] = relationship(back_populates="events")

    __table_args__ = (
        UniqueConstraint("record_id", "seq", name="uq_stage_events_record_seq"),
    )


class LLMCall(Base):
    """What lets the dashboard report the AI's share of decisions and the
    valid/invalid rate. A rubric item, not bookkeeping.

    `prompt_sha256` is the HASH, never the prompt text. The prompt contains the email
    body, and this table would otherwise become a second, unmanaged copy of the
    corpus sitting in a database with different access controls.
    """
    __tablename__ = "llm_calls"

    call_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    run_id:  Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("runs.run_id", ondelete="CASCADE"), nullable=False)
    email_id: Mapped[str | None] = mapped_column(Text)

    purpose:        Mapped[str] = mapped_column(Text, nullable=False)
    provider:       Mapped[str] = mapped_column(Text, nullable=False)
    model:          Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_sha256:  Mapped[str] = _sha()

    response_raw:   Mapped[str | None] = mapped_column(Text)
    response_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    cache_hit:      Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms:     Mapped[int | None] = mapped_column(Integer)
    error:          Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("purpose in ('classify','label_propose')",
                        name="purpose_vocab"),
        Index("ix_llm_calls_run_purpose", "run_id", "purpose"),
    )


# ------------------------------------------------------------------- HUMAN

class ReviewDecision(Base):
    """R3. NO run_id in the identity.

    A human who rules on email_013's consignee has ruled on it for good, not for one
    run. Decisions are applied at PROJECTION time, so every future run inherits them
    — which is what makes re-processing safe under R2.

    Nothing is deleted. A correction SUPERSEDES its predecessor via `superseded_by`,
    exactly as the learned-label vocabulary does.

    A record-level decision (field IS NULL) MAY bypass the monotone state rule. When
    it does, that is a deliberate human override and it must be visible: the row is
    the audit trail, and the UI is required to show it.
    """
    __tablename__ = "review_decisions"

    decision_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    email_id: Mapped[str] = mapped_column(
        Text, ForeignKey("emails.email_id"), nullable=False)
    field: Mapped[str | None] = mapped_column(Text)   # NULL = record-level

    decision_type:      Mapped[str] = mapped_column(Text, nullable=False)
    verdict:            Mapped[str | None] = mapped_column(Text)
    corrected_value:    Mapped[str | None] = mapped_column(Text)
    corrected_category: Mapped[str | None] = mapped_column(Text)
    note:               Mapped[str] = mapped_column(Text, nullable=False,
                                                    server_default="")
    reviewer:           Mapped[str] = mapped_column(Text, nullable=False)
    decided_at:         Mapped[object] = mapped_column(DateTime(timezone=True),
                                                       nullable=False,
                                                       server_default=func.now())
    superseded_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("review_decisions.decision_id"))

    __table_args__ = (
        CheckConstraint(
            "decision_type in ('confirm','correct_value','override_category',"
            "'clear_escalation','retry')", name="decision_type_vocab"),
        # The UI's hot query: the CURRENT decisions for an email. Partial, because
        # superseded rows are kept forever and would otherwise dominate the index.
        Index("ix_review_decisions_email_active", "email_id",
              postgresql_where=text("superseded_by IS NULL"),
              sqlite_where=text("superseded_by IS NULL")),
    )


class LabelProposal(Base):
    """Phase 11's queue, in the database.

    `evidence_context` is NOT NULL because a proposal with no evidence is not
    reviewable — asking someone to rule on a label with no document is asking them to
    guess, and a queue that trains its reviewer to guess is worse than no queue.
    """
    __tablename__ = "label_proposals"

    proposal_id: Mapped[int] = mapped_column(BigPK, primary_key=True, autoincrement=True)
    label_raw:        Mapped[str] = mapped_column(Text, nullable=False)
    label_normalised: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_field:   Mapped[str | None] = mapped_column(Text)
    proposed_by:      Mapped[str] = mapped_column(Text, nullable=False)  # provider:model
    prompt_version:   Mapped[str] = mapped_column(Text, nullable=False)

    evidence_doc:     Mapped[str] = mapped_column(Text, nullable=False)
    evidence_line:    Mapped[int | None] = mapped_column(Integer)
    evidence_context: Mapped[str] = mapped_column(Text, nullable=False)

    status:     Mapped[str] = mapped_column(Text, nullable=False,
                                            server_default="pending")
    decided_by: Mapped[str | None] = mapped_column(Text)   # a PERSON
    decided_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    note:       Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("status in ('pending','approved','rejected')",
                        name="status_vocab"),
        Index("ix_label_proposals_status", "status"),
    )


class LearnedLabel(Base):
    """Mirrors `config/learned_labels.yaml` exactly, including its retirement rule.

    At most ONE active row per `label_normalised`, enforced by a PARTIAL UNIQUE INDEX
    `WHERE active`. Retirement sets `active = false` and stamps `superseded_at`;
    nothing is deleted, so the history of who decided what survives.
    """
    __tablename__ = "learned_labels"

    label_normalised: Mapped[str] = mapped_column(Text, primary_key=True)
    approved_at: Mapped[object] = mapped_column(DateTime(timezone=True),
                                                primary_key=True)
    field:       Mapped[str] = mapped_column(Text, nullable=False)
    proposal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("label_proposals.proposal_id"))
    approved_by: Mapped[str] = mapped_column(Text, nullable=False)
    active:      Mapped[bool] = mapped_column(Boolean, nullable=False,
                                              server_default="true")
    superseded_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # AT MOST ONE ACTIVE ROW PER LABEL, enforced by the database rather than by
        # the code that writes it. Retirement sets active=false, so the retired rows
        # fall out of the index and the history is kept.
        Index("uq_learned_labels_active", "label_normalised", unique=True,
              postgresql_where=text("active"),
              sqlite_where=text("active")),
    )


# ------------------------------------------------------------------ OUTPUT

class Submission(Base):
    """The deliverable, stored whole with its hash.

    Storing the payload AND the hash is redundant on purpose: the hash is what gate 3
    compares against the file on disk, and computing it from the JSONB at query time
    would depend on the database's key ordering rather than on what we actually wrote.
    """
    __tablename__ = "submissions"

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True)
    payload:    Mapped[dict] = mapped_column(JSONBType, nullable=False)
    sha256:     Mapped[str] = _sha()
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True),
                                               nullable=False,
                                               server_default=func.now())


class Evaluation(Base):
    """R5. SCORES ONLY.

    There is no table for gold labels and there must never be one. The answer key
    lives outside this repository; `eval/evaluate.py` reads it, computes these six
    numbers with the organisers' own scoring.py, and writes only the numbers here.
    `tests/property/test_no_answer_key_leak.py` covers this package.
    """
    __tablename__ = "evaluations"

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("runs.run_id", ondelete="CASCADE"), primary_key=True)
    macro_f1:      Mapped[object | None] = mapped_column(Numeric(6, 4))
    defect_f1:     Mapped[object | None] = mapped_column(Numeric(6, 4))
    end_to_end:    Mapped[object | None] = mapped_column(Numeric(6, 4))
    reliability_p: Mapped[object | None] = mapped_column(Numeric(6, 4))
    reliability_r: Mapped[object | None] = mapped_column(Numeric(6, 4))
    final_score:   Mapped[object | None] = mapped_column(Numeric(6, 4))
    evaluated_at:  Mapped[object] = mapped_column(DateTime(timezone=True),
                                                  nullable=False,
                                                  server_default=func.now())
