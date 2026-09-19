"""M13 — orchestration. Sits above everything and imports freely.

Two rules carry the design here:
  * `run_stage` is one of exactly two broad `except Exception` sites, and its FAILED
    assignment is UNCONDITIONAL — v1.0's `if state is None` preserved a half-assigned
    RESOLVED when the evaluator raised after setting it.
  * The pipeline SHORT-CIRCUITS after an escalating stage. v1.0 ran every stage
    unconditionally, which is how an escalated record still reached `evaluate` with an
    empty comparison map.
"""
from __future__ import annotations

import json
import os
import tempfile
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

from shipdoc.adapters.submission import SubmissionAdapter
from shipdoc.errors import ShipdocError, reason_key
from shipdoc.state.machine import evaluate
from shipdoc.types import (
    Config,
    Decision,
    Record,
    RecordState,
    ReasonKey,
    StageEvent,
)


def _halted(rec: Record) -> bool:
    """True iff a stage escalated or failed.

    Exact, and it depends on HARD RULE 4: before `evaluate` runs, the only writer of
    `state` is `run_stage`. `tests/test_registry_guard.py` asserts that rule rather
    than trusting it.
    """
    return rec.state is not None


def run_stage(rec: Record, fn: Callable[[Record, Config], Record],
              name: str, cfg: Config) -> Record:
    """The ONLY broad `except Exception` outside the extractor decorator."""
    try:
        return fn(rec, cfg)
    except ShipdocError as e:
        from shipdoc.state.machine import raise_state
        raise_state(rec, RecordState.ESCALATED, reason_key(e))
        rec.trace.append(StageEvent(name, "escalated", str(e), seq=len(rec.trace)))
        return rec
    except Exception as e:  # noqa: BLE001 — deliberate, see docstring
        rec.state, rec.reason = RecordState.FAILED, ReasonKey.ERR_UNHANDLED
        rec.trace.append(
            StageEvent(name, "failed", f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                       seq=len(rec.trace)))
        return rec


def stage_classify(rec: Record, cfg: Config) -> Record:
    from shipdoc.classify.arbiter import classify
    category, confidence = classify(rec, cfg, _LLM.get("client"))
    rec.category = category
    rec.trace.append(StageEvent(
        "classify", "ok" if category else "undecided",
        f"{category} conf={confidence:.2f}", seq=len(rec.trace)))
    return rec


# The LLM handle is threaded through a module-level slot rather than through every
# stage signature, because `run_stage` fixes the stage signature at (rec, cfg).
_LLM: dict[str, Any] = {"client": None}


def stage_route(rec: Record, cfg: Config) -> Record:
    from shipdoc.classify.intent import awaiting_documents
    from shipdoc.route.by_name import route_by_name

    # An attachment-free comparison request is usually the shipper ASKING for the
    # draft BL, not a broken submission. Decide from the body before calling it a
    # missing attachment (review item: the queue was 85 of these).
    if not (rec.raw.get("attachments") or ()) and awaiting_documents(rec):
        rec.awaiting_docs = True
        rec.trace.append(StageEvent("route", "ok", "awaiting_documents",
                                    seq=len(rec.trace)))
        return rec

    _CTX["roles"][rec.email_id] = route_by_name(rec)
    return rec


def stage_extract(rec: Record, cfg: Config) -> Record:
    from shipdoc.detect.mime import detect
    from shipdoc.errors import ExtractionError

    inbox, registry = _CTX["inbox"], _CTX["registry"]
    for role, path in _CTX["roles"][rec.email_id].items():
        data = inbox.read_bytes(path)
        det = detect(data, path)
        if det.disagrees:
            # A signal, recorded — never a failure. It may be the planted
            # wrong_doc_type case, or a customer whose export names files badly.
            rec.trace.append(StageEvent(
                "detect", "ok",
                f"{path}: claimed {det.extension_claimed}, detected {det.mime}",
                seq=len(rec.trace)))
        doc = registry.extract(data, path, det.mime,
                               cfg.thresholds.min_extract_chars,
                               cache=_CTX["doccache"])
        rec.documents[role] = doc
        if not doc.ok:
            raise ExtractionError(f"{path}: {doc.failure}")
    return rec


def stage_confirm(rec: Record, cfg: Config) -> Record:
    from shipdoc.route.confirm import confirm_doc_type
    confirm_doc_type(rec.documents, cfg, _CTX["label_index"])
    return rec


def stage_normalise(rec: Record, cfg: Config) -> Record:
    normaliser = _CTX["normaliser"]
    for role, doc in rec.documents.items():
        rec.fields[role] = normaliser.normalise(
            doc, _CTX["roles"][rec.email_id].get(role, role))
    return rec


def stage_compare(rec: Record, cfg: Config) -> Record:
    from shipdoc.compare.comparators import compare_all
    # Flag OFF => the resolver is not passed, so cmp_port takes the pre-Phase-5
    # string path exactly. Not an equivalent path — the same one.
    resolver = (_CTX["normaliser"].ports
                if cfg.flags.port_resolution_enabled else None)
    rec.comparisons = compare_all(rec.fields.get("SI", {}), rec.fields.get("BL", {}),
                                  cfg, resolver)
    return rec


# Per-run collaborators the (rec, cfg) stage signature cannot carry.
_CTX: dict[str, Any] = {"inbox": None, "registry": None, "normaliser": None,
                        "roles": {}, "doccache": None, "cache_dir": None,
                        "label_index": None}


def process(rec: Record, cfg: Config, llm: Any,
            decisions: Mapping[tuple[str, str], Decision]) -> Record:
    """Per-record stage sequence.

    The SHORT-CIRCUIT is load-bearing: v1.0 ran every stage unconditionally after a
    raising stage, which is how an escalated record still reached `evaluate` with an
    empty comparison map and was reported clean.

    """
    _LLM["client"] = llm
    rec = run_stage(rec, stage_classify, "classify", cfg)

    if rec.category == cfg.comparison_category and rec.state is not RecordState.FAILED:
        for fn, name in ((stage_route, "route"), (stage_extract, "extract"),
                         (stage_confirm, "confirm"), (stage_normalise, "normalise"),
                         (stage_compare, "compare")):
            if _halted(rec) or rec.awaiting_docs:
                break
            rec = run_stage(rec, fn, name, cfg)

    # Decisions are an INPUT, applied before evaluate so a human answer can move a
    # record out of escalation in the same single pass.
    from shipdoc.review.queue import apply_decisions
    rec = apply_decisions(rec, decisions)

    rec = evaluate(rec, cfg)                      # the ONLY state authority
    assert rec.state is not None, f"T1 violated: {rec.email_id}"
    return rec


def run_corpus(inbox, cfg: Config, llm: Any = None,
               decisions: Mapping[tuple[str, str], Decision] | None = None,
               cache_dir: Path | str | None = None) -> dict:
    """Process the whole corpus and project it. Returns the artifacts, unwritten."""
    decisions = decisions or {}
    emails = list(inbox.emails())
    corpus_ids = [e["email_id"] for e in emails]

    degraded_reasons: list[str] = []
    if llm is None:
        degraded_reasons.append("llm_unavailable_semantic_classification")

    from shipdoc.extract.registry import default_registry
    from shipdoc.normalise import Normaliser
    from shipdoc.normalise.labels import LabelIndex
    _CTX["inbox"] = inbox
    _CTX["registry"] = default_registry(ocr_enabled=cfg.flags.ocr_enabled)
    # Built once and shared by both documents: normalising in two places is the
    # classic source of guaranteed false alarms (M09).
    _CTX["normaliser"] = Normaliser(cfg)
    # route/confirm.py needs label matching but may not import `normalise` (v2 §3
    # puts normalise above route). The orchestrator sits above both and owns
    # construction. Built ONCE and reused: LabelIndex assigns state only in
    # __init__ — match() and is_any_label() are pure reads — and Normaliser already
    # builds one per run and reuses it across all 520 records.
    _CTX["label_index"] = LabelIndex(cfg)
    _CTX["roles"] = {}

    from shipdoc.infra.cache import Cache
    from shipdoc.infra.doccache import DocCache
    cache_dir = cache_dir or _CTX.get("cache_dir")
    _CTX["doccache"] = DocCache(Cache(Path(cache_dir) / "extract")) if cache_dir \
        else DocCache(None)

    records = [process(Record(email_id=e["email_id"], raw=e), cfg, llm, decisions)
               for e in emails]

    assert len(records) == len(corpus_ids), "record count diverged from the corpus"

    submission = SubmissionAdapter().emit(records, expected_ids=corpus_ids)
    return {
        "records": records,
        "submission": submission,
        "summary": summarise(records, degraded_reasons),
    }


def summarise(records: list[Record], degraded_reasons: list[str]) -> dict:
    """The operational metrics artifact. Structured counts, never prose — these are
    what a GROUP BY runs over.

    Counters use the INTERNAL reason vocabulary (`err_no_value`), not the external
    `review_reason` spellings: this is an operations artifact, not a submission, and
    conflating the two would undo the boundary patch §5 established.

    Deterministic by construction: counts only, no wall-clock time, no random ids.
    Both counters are zero-filled from their enums so a metric never silently vanishes
    from the output just because no record hit it this run.
    """
    by_state = {s.value: 0 for s in RecordState}
    by_state.update(Counter(r.state.value for r in records if r.state is not None))

    by_reason = {k.value: 0 for k in ReasonKey}
    by_reason.update(Counter(r.reason.value for r in records if r.reason is not None))

    return {
        "records_total":    len(records),
        "by_state":         by_state,
        "by_reason":        by_reason,
        "degraded":         bool(degraded_reasons),
        "degraded_reasons": sorted(degraded_reasons),
        "baseline":         None,
    }


def write_atomic(path: Path, payload: object) -> None:
    """Temp file plus rename: a killed process must not leave a half-written artifact
    that deserialises into garbage on the next run."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # sort_keys=False deliberately: entries must keep sample_submission.json's
            # field order. Determinism (I6) comes from callers emitting in sorted
            # email_id order, not from re-sorting every nested object.
            json.dump(payload, fh, indent=2, sort_keys=False, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


LLM_CACHE_DIR = Path("cache") / "llm"


def build_llm(cfg: Config, out_dir: Path, cache_dir: Path | None = None):
    """Construct the cached client, probing once so degraded mode is entered a single
    time rather than 394 times.

    Returns a CachedLLM whenever the cache exists, even with no model reachable: a
    warm cache answers every prompt this corpus asks, so a clone with no Ollama still
    reproduces the published run. Returns None only when there is neither.
    """
    from shipdoc.infra.cache import Cache
    from shipdoc.llm.client import CachedLLM, OllamaClient, probe

    root = Path(cache_dir) if cache_dir else LLM_CACHE_DIR
    inner = OllamaClient(cfg.llm.model, temperature=cfg.llm.temperature,
                         seed=cfg.llm.seed)
    client = CachedLLM(inner, Cache(root), prompt_version=cfg.llm.prompt_version,
                       model=cfg.llm.model)

    if probe(inner, timeout_s=min(cfg.llm.timeout_s, 15.0)):
        return client
    # No server. If the cache has entries they are this model's own answers at
    # temperature 0, so they are exactly what the server would have returned.
    return client if root.is_dir() and any(root.rglob("*")) else None


def main_run(source: str, config_dir: str, out_dir: str,
             submit: bool = False, server_url: str | None = None,
             no_llm: bool = False) -> dict:
    """Entry point for the CLI. Returns the run summary."""
    from shipdoc.config import load_config
    from shipdoc.ingest.loader_port import LoaderInbox

    from shipdoc.review.queue import load_decisions, read_raw, write_queue

    cfg = load_config(Path(config_dir))
    inbox = LoaderInbox(source)
    llm = None if no_llm else build_llm(cfg, Path(out_dir))

    # P-HANDOFF: ONE file. The queue the reviewer was handed is the queue we read.
    queue_path = Path(out_dir) / "review_queue.json"
    prior = read_raw(queue_path)
    decisions = load_decisions(queue_path)

    # Extraction cache lives beside the LLM cache, under the run's out dir.
    _CTX["cache_dir"] = Path(out_dir) / "cache"
    result = run_corpus(inbox, cfg, llm=llm, decisions=decisions)

    from shipdoc.adapters.report import ReportAdapter

    out = Path(out_dir)
    write_atomic(out / "submission.json", result["submission"])
    write_atomic(out / "run_summary.json", result["summary"])

    write_queue(result["records"], queue_path, preserve=prior)
    result["summary"]["decisions_applied"] = len(decisions)
    write_atomic(out / "run_summary.json", result["summary"])

    try:
        from shipdoc.llm.client import write_manifest
        write_manifest(LLM_CACHE_DIR, cfg.llm.model, cfg.llm.prompt_version)
    except Exception:
        pass                      # a manifest must never fail a run

    report = ReportAdapter().emit(result["records"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.txt").write_text(report, encoding="utf-8")

    # report.txt is written above (stage 4).
    # v2 reorder dropped adapters/report from the build sequence when pass 2 was
    # deleted. It lands at stage 4, when real SI/BL values first exist to put
    # side by side. The scoreboard cannot measure this output, which is exactly why
    # it is easy to forget.

    if submit:
        target = LoaderInbox(server_url) if server_url else inbox
        scoreboard = target.submit(result["submission"])
        write_atomic(out / "scoreboard.json", scoreboard)
        result["summary"]["baseline"] = scoreboard.get("final_score")
        write_atomic(out / "run_summary.json", result["summary"])

    return result["summary"]
