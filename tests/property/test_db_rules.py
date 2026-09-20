"""Phase 13 — the five database rules, asserted rather than documented.

Each test below is named for the rule it protects. A rule that lives only in a
docstring is a rule the next person removes by accident.

Everything here runs on SQLite, so the suite and the clean-clone gate need no
database server. The PostgreSQL-specific behaviour (JSONB, partial indexes) is
exercised separately by the migration against a real server; what is checked here is
the LOGIC, which is identical on both.
"""
from __future__ import annotations

import ast
import os
import uuid
from pathlib import Path

import pytest

from conftest import ROOT

pytest.importorskip("sqlalchemy")

SRC = ROOT / "src" / "shipdoc"
DB_PKG = SRC / "adapters" / "db"

# The core. R1 says none of these may reach the database.
CORE_PACKAGES = ("ingest", "detect", "extract", "route", "normalise", "compare",
                 "state", "classify")


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
    return out


# ------------------------------------------------------- R1: IT IS AN ADAPTER

def test_r1_no_core_module_imports_the_database():
    """The database must not leak downward into the pipeline.

    `test_layering.py` already forbids every leftward import and catches this as a
    side effect. This test names the rule explicitly, so that if the layer list is
    ever reordered the intent survives as its own assertion rather than as a
    coincidence.
    """
    offenders = []
    for pkg in CORE_PACKAGES:
        d = SRC / pkg
        if not d.is_dir():
            continue
        for p in d.rglob("*.py"):
            for mod in _imports(p):
                if "adapters.db" in mod or mod.endswith("adapters"):
                    offenders.append(f"{pkg}/{p.name} imports {mod}")
    assert not offenders, "the database leaked into the core:\n  " + "\n  ".join(offenders)


def test_r1_the_database_package_does_not_import_the_core():
    """The adapter may know about `types`, and nothing else from the pipeline.

    An adapter that imports `compare` or `state` has stopped being a boundary and
    become a second place where the rules live.
    """
    allowed = {"shipdoc.types", "shipdoc.errors", "shipdoc.adapters.db",
               "shipdoc.ingest.loader_port"}   # seed reads the corpus, by design
    offenders = []
    for p in DB_PKG.rglob("*.py"):
        for mod in _imports(p):
            if not mod.startswith("shipdoc"):
                continue
            if any(mod.startswith(a) for a in allowed):
                continue
            offenders.append(f"{p.name} imports {mod}")
    assert not offenders, "adapter reaches into the core:\n  " + "\n  ".join(offenders)


def test_import_shipdoc_works_without_sqlalchemy(monkeypatch):
    """`sqlalchemy` is an OPTIONAL extra. Importing the db package must not cost it."""
    import importlib
    import shipdoc.adapters.db as db
    importlib.reload(db)
    assert db.build_repository(None) is None


# ------------------------------------------------- R5: NO GOLD LABELS, EVER

def test_r5_no_adapter_module_references_the_answer_key():
    """There is no table for gold labels and no code path that could read them."""
    markers = ("ground_truth", "ground-truth", "data_v2")
    offenders = []
    for p in (SRC / "adapters").rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in markers:
                    if m in node.value:
                        offenders.append(f"{p.name}: {node.value[:60]!r}")
    assert not offenders, "answer key referenced by an adapter:\n  " + "\n  ".join(offenders)


def test_r5_there_is_no_table_for_gold_labels():
    from shipdoc.adapters.db.models import Base
    tables = set(Base.metadata.tables)
    for forbidden in ("ground_truth", "gold", "labels_gold", "answers", "truth"):
        assert forbidden not in tables
    # `evaluations` exists and holds SCORES only — no per-record label column.
    cols = set(Base.metadata.tables["evaluations"].columns.keys())
    assert cols == {"run_id", "macro_f1", "defect_f1", "end_to_end",
                    "reliability_p", "reliability_r", "final_score", "evaluated_at"}


def test_r5_the_repository_has_no_method_that_stores_labels():
    from shipdoc.adapters.db.sqlstore import SQLRepository
    names = [n for n in dir(SQLRepository) if not n.startswith("_")]
    for n in names:
        assert "gold" not in n and "truth" not in n and "answer" not in n, n


# ------------------------------------------------------------- the repository

@pytest.fixture()
def repo(tmp_path):
    from shipdoc.adapters.db.sqlstore import SQLRepository
    return SQLRepository(f"sqlite:///{tmp_path / 'test.db'}")


def _run_input(**kw):
    from shipdoc.adapters.db.repository import RunInput
    base = dict(
        code_version="abc123", config_sha256="0" * 64,
        submission={"email_001": {"status": "OK"}},
        submission_sha256="1" * 64,
        records=[{"email_id": "email_001", "category": "BL_COMPARISON",
                  "decided_by": "rule", "state": "resolved", "status": "OK",
                  "has_defect": False,
                  "comparisons": [{"field": "shipper", "verdict": "MATCH",
                                   "si_value": "ACME", "bl_value": "ACME"}],
                  "events": [{"seq": 0, "stage": "classify", "outcome": "ok"}]}],
    )
    base.update(kw)
    return RunInput(**base)


def test_r2_reprocessing_creates_a_new_run_and_never_updates_the_old(repo):
    """R2: a finished run's rows are immutable. History is the point."""
    first = repo.save_run(_run_input())
    second = repo.save_run(_run_input(submission_sha256="2" * 64))
    assert first != second

    from shipdoc.adapters.db.models import Run
    from sqlalchemy import select
    with repo.session() as s:
        runs = list(s.scalars(select(Run)))
    assert len(runs) == 2, "re-processing must INSERT, never overwrite"
    assert {r.submission_sha256 for r in runs} == {"1" * 64, "2" * 64}


def test_r2_there_is_no_updated_at_column_anywhere():
    """An `updated_at` is an invitation to mutate a finished run."""
    from shipdoc.adapters.db.models import Base
    for name, table in Base.metadata.tables.items():
        assert "updated_at" not in table.columns, name


def test_r4_a_run_records_what_produced_it(repo):
    """Without these a changed score has no explanation three weeks later."""
    run_id = repo.save_run(_run_input(
        learned_labels_sha256="a" * 64, decisions_sha256="b" * 64,
        llm_provider="deepseek", llm_model="deepseek-chat", prompt_version="v1"))
    from shipdoc.adapters.db.models import Run
    with repo.session() as s:
        r = s.get(Run, run_id)
    assert r.code_version and r.config_sha256
    assert r.learned_labels_sha256 == "a" * 64
    assert r.decisions_sha256 == "b" * 64
    assert (r.llm_provider, r.llm_model, r.prompt_version) == \
           ("deepseek", "deepseek-chat", "v1")


def test_r3_decisions_carry_no_run_id_and_outlive_runs(repo):
    """A human who ruled on a field ruled on it for good, not for one run."""
    from shipdoc.adapters.db.models import ReviewDecision
    assert "run_id" not in ReviewDecision.__table__.columns

    repo.save_run(_run_input())
    did = repo.record_decision("email_001", "shipper", "confirm", "a.reviewer",
                               verdict="MATCH", note="checked by hand")
    assert did > 0
    # A NEW run later must not disturb it.
    repo.save_run(_run_input(submission_sha256="3" * 64))
    active = repo.list_decisions("email_001")
    assert len(active) == 1 and active[0]["reviewer"] == "a.reviewer"


def test_r3_a_correction_supersedes_and_nothing_is_deleted(repo):
    repo.save_run(_run_input())
    repo.record_decision("email_001", "shipper", "confirm", "first", verdict="MATCH")
    repo.record_decision("email_001", "shipper", "correct_value", "second",
                         corrected_value="ACME LTD")
    active = repo.list_decisions("email_001")
    assert len(active) == 1 and active[0]["reviewer"] == "second"
    everything = repo.list_decisions("email_001", include_superseded=True)
    assert len(everything) == 2, "the earlier ruling must still be on record"


def test_a_record_level_decision_is_allowed_and_distinguishable(repo):
    """field IS NULL means record-level; it MAY bypass the monotone state rule, so
    it has to be visible as its own thing."""
    repo.save_run(_run_input())
    repo.record_decision("email_001", None, "clear_escalation", "a.reviewer",
                         note="spoke to the carrier")
    rows = repo.list_decisions("email_001")
    assert rows[0]["field"] is None
    assert rows[0]["decision_type"] == "clear_escalation"


def test_submission_payload_round_trips_intact(repo):
    payload = {"email_001": {"status": "MISMATCH", "defect_fields": ["shipper"],
                             "has_defect": True, "review_reason": None}}
    run_id = repo.save_run(_run_input(submission=payload))
    assert repo.get_submission(run_id)["payload"] == payload


def test_record_detail_carries_evidence_and_decisions(repo):
    repo.save_run(_run_input())
    repo.record_decision("email_001", "shipper", "confirm", "a.reviewer")
    detail = repo.get_record_detail("email_001")
    assert detail["email_id"] == "email_001"
    assert detail["comparisons"][0]["field"] == "shipper"
    assert detail["events"][0]["stage"] == "classify"
    assert detail["decisions"][0]["reviewer"] == "a.reviewer"


def test_list_records_filters_map_to_declared_indexes(repo):
    from shipdoc.adapters.db.repository import RecordFilter
    repo.save_run(_run_input())
    assert len(repo.list_records(RecordFilter(status="OK"))) == 1
    assert len(repo.list_records(RecordFilter(status="MISMATCH"))) == 0
    assert len(repo.list_records(RecordFilter(category="BL_COMPARISON"))) == 1


# --------------------------------------------------------- proposals & labels

def _proposal(repo, label="Containers:", field="container_count"):
    from shipdoc.learned import normalise_label
    return repo.add_proposal(
        label_raw=label, label_normalised=normalise_label(label),
        proposed_field=field, proposed_by="deepseek:deepseek-chat",
        prompt_version="labels-v1", evidence_doc="d.pdf", evidence_line=4,
        evidence_context="Containers: 3 x 40'HC")


def test_a_proposal_with_no_evidence_is_refused(repo):
    """Same rule as the file queue: asking someone to rule with no document is
    asking them to guess."""
    assert repo.add_proposal(
        label_raw="X:", label_normalised="x", proposed_field="shipper",
        proposed_by="m", prompt_version="v", evidence_doc="", evidence_line=0,
        evidence_context="") is None


def test_one_label_one_proposal_once_ever(repo):
    assert _proposal(repo) is not None
    assert _proposal(repo) is None


def test_approving_a_proposal_requires_a_persons_name(repo):
    pid = _proposal(repo)
    with pytest.raises(ValueError, match="PERSON"):
        repo.decide_proposal(pid, "approved", "")


def test_approval_creates_exactly_one_active_learned_label(repo):
    pid = _proposal(repo)
    repo.decide_proposal(pid, "approved", "a.real.person", note="checked")
    active = repo.active_learned_labels()
    assert len(active) == 1
    assert active[0]["field"] == "container_count"
    assert active[0]["approved_by"] == "a.real.person"


def test_reapproval_retires_the_previous_row_without_deleting_it(repo):
    """Mirrors the YAML behaviour exactly: at most one ACTIVE row, history kept."""
    from shipdoc.adapters.db.models import LearnedLabel
    from sqlalchemy import select

    pid = _proposal(repo)
    repo.decide_proposal(pid, "approved", "first.person")
    # A second proposal for the same label, decided again.
    with repo.session() as s, s.begin():
        from shipdoc.adapters.db.models import LabelProposal
        s.add(LabelProposal(label_raw="Containers:", label_normalised="containers",
                            proposed_field="container_count", proposed_by="m",
                            prompt_version="v", evidence_doc="d", evidence_line=1,
                            evidence_context="c"))
    with repo.session() as s:
        second = s.scalars(select(LabelProposal)
                           .order_by(LabelProposal.proposal_id.desc())).first()
    repo.decide_proposal(second.proposal_id, "approved", "second.person")

    assert len(repo.active_learned_labels()) == 1
    assert repo.active_learned_labels()[0]["approved_by"] == "second.person"
    with repo.session() as s:
        allrows = list(s.scalars(select(LearnedLabel)))
    assert len(allrows) == 2, "the retired row must be kept, not deleted"
    assert sum(1 for r in allrows if r.active) == 1


def test_rejection_does_not_create_a_learned_label(repo):
    pid = _proposal(repo, "Vessel Name", "gross_weight_kg")
    repo.decide_proposal(pid, "rejected", "a.real.person", note="that is a vessel")
    assert repo.active_learned_labels() == []
    assert repo.list_proposals("rejected")[0]["decided_by"] == "a.real.person"


# ------------------------------------------------------------- scores only

def test_evaluation_stores_scores_as_numeric_not_float(repo):
    from decimal import Decimal
    from shipdoc.adapters.db.models import Evaluation
    run_id = repo.save_run(_run_input())
    repo.save_evaluation(run_id, {"macro_f1": 0.9526, "defect_f1": 1.0,
                                  "end_to_end": 1.0, "final_score": 0.9858})
    with repo.session() as s:
        row = s.get(Evaluation, run_id)
    assert isinstance(row.final_score, Decimal), "NUMERIC, never FLOAT"
    assert str(row.final_score) == "0.9858"
    assert repo.latest_evaluation()["final_score"] == 0.9858
