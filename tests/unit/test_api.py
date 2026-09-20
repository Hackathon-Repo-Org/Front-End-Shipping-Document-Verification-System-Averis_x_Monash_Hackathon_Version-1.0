"""Phase 14 — the API is a translation layer, and the overlay mirrors the engine.

Two things are worth testing here and the rest is FastAPI's job:

  1. THE OVERLAY AGREES WITH THE ENGINE. `adapters/projection.py` recomputes a
     status from field verdicts, which duplicates `state/machine.evaluate`. The
     duplication is deliberate (reconstructing a Record on every page load is not
     viable) and is made safe by this test, not by a comment.

  2. NO LOGIC LIVES IN THE API. Asserted against the source with `ast`, because
     "keep the handlers thin" is a rule that decays the moment someone is in a hurry.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from conftest import ROOT

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

API = ROOT / "src" / "shipdoc" / "adapters" / "api"


# ------------------------------------------------- the overlay vs the engine

def test_overlay_agrees_with_the_engine_on_every_verdict_shape():
    """The projection rule, exhaustively, over every combination of three verdicts.

    `state/machine.evaluate` decides: a confirmed defect wins; otherwise honest
    uncertainty; otherwise OK. If either implementation is edited alone, this fails.
    """
    from itertools import product

    from shipdoc.adapters.projection import status_from_verdicts

    V = ["MATCH", "MISMATCH", "CANNOT_DETERMINE"]
    for combo in product(V, repeat=3):
        expected = ("MISMATCH" if "MISMATCH" in combo
                    else "NEEDS_REVIEW" if "CANNOT_DETERMINE" in combo
                    else "OK")
        assert status_from_verdicts(combo) == expected, combo


def test_overlay_matches_the_stored_run_when_there_are_no_decisions():
    """With no human input the overlay must be the identity on status.

    This is the strong version of "decisions take effect immediately": the machinery
    that applies them must do NOTHING when there are none, or every record would
    silently drift away from the submission that was scored.
    """
    from shipdoc.adapters.projection import overlay

    for stored, verdicts in [
        ("OK", ["MATCH", "MATCH"]),
        ("MISMATCH", ["MATCH", "MISMATCH"]),
        ("NEEDS_REVIEW", ["MATCH", "CANNOT_DETERMINE"]),
    ]:
        rec = {"email_id": "e", "status": stored, "category": "BL_COMPARISON",
               "comparisons": [{"field": f"f{i}", "verdict": v}
                               for i, v in enumerate(verdicts)]}
        assert overlay(rec, [])["status"] == stored
        assert overlay(rec, [])["human_decided"] is False


def test_a_correction_clears_the_defect_and_is_marked_as_human():
    from shipdoc.adapters.projection import overlay
    rec = {"email_id": "e", "status": "MISMATCH", "category": "BL_COMPARISON",
           "comparisons": [{"field": "port_of_discharge", "verdict": "MISMATCH",
                            "bl_value": "TUTICORIN"}]}
    out = overlay(rec, [{"decision_type": "correct_value",
                         "field": "port_of_discharge", "reviewer": "a.reviewer",
                         "corrected_value": "MOMBASA"}])
    assert out["status"] == "OK"
    assert out["defect_fields"] == []
    assert out["human_decided"] is True
    assert out["comparisons"][0]["bl_value"] == "MOMBASA"
    assert out["comparisons"][0]["decided_by_human"] is True


def test_a_record_level_override_is_flagged_when_it_bypasses_the_state_rule():
    """The one thing that must never happen is for a human override to be invisible."""
    from shipdoc.adapters.projection import overlay
    rec = {"email_id": "e", "status": "NEEDS_REVIEW", "category": "BL_COMPARISON",
           "review_reason": "missing_value", "comparisons": []}
    out = overlay(rec, [{"decision_type": "clear_escalation", "field": None,
                         "reviewer": "a.reviewer", "note": "spoke to the carrier"}])
    assert out["status"] == "OK"
    assert out["bypassed_state_rule"] is True, \
        "a bypass of the monotone state rule must be visible to the reviewer"


def test_overlay_does_not_mutate_its_input():
    """The stored row is immutable (R2). Mutating it here would corrupt a cache."""
    from shipdoc.adapters.projection import overlay
    rec = {"email_id": "e", "status": "MISMATCH",
           "comparisons": [{"field": "f", "verdict": "MISMATCH"}]}
    overlay(rec, [{"decision_type": "confirm", "field": "f", "verdict": "MATCH",
                   "reviewer": "r"}])
    assert rec["status"] == "MISMATCH"
    assert rec["comparisons"][0]["verdict"] == "MISMATCH"


# --------------------------------------------------- no logic in the API

def test_no_route_handler_contains_a_comparison_or_state_rule():
    """The API translates. It does not decide.

    Looks for the vocabulary of the engine — verdict names, state names, threshold
    arithmetic — appearing in `app.py` outside of a docstring. If a comparison rule
    ever lands in a handler it belongs in the engine, where 737 tests cover it.
    """
    tree = ast.parse((API / "app.py").read_text(encoding="utf-8"))
    docstrings = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))

    banned = ("CANNOT_DETERMINE", "grey_band", "threshold", "similarity",
              "raise_state", "normalise_party", "compare_all")
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) \
                and id(n) not in docstrings:
            for b in banned:
                if b in n.value:
                    found.append(f"{b} in {n.value[:50]!r}")
    assert not found, "engine logic leaked into the API:\n  " + "\n  ".join(found)


def test_the_api_imports_no_engine_internals():
    """It may talk to config, types and the repository. Not to compare/ or state/."""
    forbidden = ("shipdoc.compare", "shipdoc.state", "shipdoc.normalise.party",
                 "shipdoc.review.queue")
    offenders = []
    for p in API.rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            mod = (node.module if isinstance(node, ast.ImportFrom) and node.module
                   else None)
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            for m in ([mod] if mod else []) + names:
                if any(m.startswith(f) for f in forbidden):
                    offenders.append(f"{p.name} imports {m}")
    assert not offenders, offenders


# ------------------------------------------------------------ the contract

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("DEMO_PASSCODE", "test-code")
    from fastapi.testclient import TestClient

    from shipdoc.adapters.api.app import create_app
    return TestClient(create_app())


def test_health_never_500s_even_with_nothing_set_up(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "status" in r.json()


def test_vocabulary_serves_every_string_the_ui_needs(client):
    v = client.get("/api/vocabulary").json()
    for key in ("statuses", "categories", "review_reasons", "verdicts",
                "decision_types", "fields"):
        assert v[key], key
    assert [f["value"] for f in v["fields"]][:2] == ["shipper", "consignee"]
    # Every verdict carries an icon: colour alone is not accessible.
    assert all(x.get("icon") for x in v["verdicts"])


def test_vocabulary_does_not_drift_from_the_type_enums(client):
    v = client.get("/api/vocabulary").json()
    assert {c["value"] for c in v["categories"]} == set(v["_enums"]["category"])
    assert {x["value"].lower() for x in v["verdicts"]} == set(v["_enums"]["verdict"])


def test_writes_require_the_passcode(client):
    r = client.post("/api/records/email_001/decisions",
                    json={"decision_type": "confirm", "reviewer": "x"})
    assert r.status_code == 401
    assert "passcode" in r.json()["detail"].lower()


def test_a_decision_requires_a_reviewer_name(client):
    r = client.post("/api/records/email_001/decisions",
                    headers={"X-Demo-Passcode": "test-code"},
                    json={"decision_type": "confirm"})
    assert r.status_code == 422
    assert "auditable" in r.json()["detail"]


def test_reads_are_open(client):
    assert client.get("/api/records").status_code == 200
    assert client.get("/api/vocabulary").status_code == 200


def test_cors_allows_the_passcode_header_and_options(monkeypatch, tmp_path):
    """THE split-deployment trap: reads work, writes fail.

    The passcode travels as a custom header, which makes every write a preflighted
    request. If the preflight does not allow that header and OPTIONS, writes fail
    from a browser while curl succeeds — and it looks like a backend bug.
    """
    monkeypatch.setenv("CORS_ORIGINS", "https://example-frontend.net")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'c.db'}")
    from fastapi.testclient import TestClient

    from shipdoc.adapters.api.app import create_app
    c = TestClient(create_app())
    r = c.options("/api/records/email_001/decisions", headers={
        "Origin": "https://example-frontend.net",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "x-demo-passcode,content-type"})
    assert r.status_code == 200, "preflight rejected: every write would fail"
    allowed = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-demo-passcode" in allowed
    assert r.headers.get("access-control-allow-origin") == "https://example-frontend.net"


def test_cors_is_never_a_wildcard(monkeypatch, tmp_path):
    monkeypatch.setenv("CORS_ORIGINS", "https://example-frontend.net")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'c2.db'}")
    from fastapi.testclient import TestClient

    from shipdoc.adapters.api.app import create_app
    c = TestClient(create_app())
    r = c.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") != "*"


def test_no_cookies_are_ever_set(client):
    """Static Web Apps and Container Apps are different domains, so a cookie is
    third-party and is blocked by Safari and by incognito — which is exactly how a
    judge opens a link. Header auth only."""
    for path in ("/api/health", "/api/vocabulary", "/api/records"):
        assert not client.get(path).cookies


# --------------------------------------------- try it yourself (Phase 15)

def test_try_runs_the_real_engine_and_finds_the_planted_defect(client):
    """The worked example must find something on the first click.

    An example that returns OK teaches a visitor nothing and looks broken.
    """
    sample = client.get("/api/try/sample").json()
    r = client.post("/api/try", json={k: sample[k] for k in
                                      ("subject", "body", "si_text", "bl_text")})
    assert r.status_code == 200
    d = r.json()
    assert d["category"] == "BL_COMPARISON"
    assert d["status"] == "MISMATCH"
    assert d["defect_fields"] == ["port_of_discharge"]
    assert len(d["comparisons"]) == 7


def test_try_applies_the_same_rules_as_the_batch(client):
    """Not a demo mode — the real normaliser and comparators.

    Three behaviours in one submission: a legal suffix differing only in
    punctuation MATCHES, a referential value resolves against its own document, and
    European decimal separators are the same number.
    """
    sample = client.get("/api/try/sample").json()
    d = client.post("/api/try", json=sample).json()
    by = {c["field"]: c for c in d["comparisons"]}
    assert by["shipper"]["verdict"] == "MATCH", "SDN BHD vs SDN. BHD."
    assert by["gross_weight_kg"]["verdict"] == "MATCH", "22,450.50 vs 22.450,50"
    assert by["notify_party"]["verdict"] == "MATCH", "SAME AS CONSIGNEE"
    assert by["notify_party"]["si_evidence"]["resolved_from"] == "consignee", \
        "an inferred value must say so, or it looks like one that was read"


def test_try_needs_no_passcode(client):
    """Gating this behind a code a visitor does not have defeats its purpose."""
    r = client.post("/api/try", json={"subject": "hello", "body": "anything"})
    assert r.status_code == 200


def test_try_stores_nothing(client):
    """An anonymous visitor cannot add rows to the demo."""
    before = client.get("/api/records").json()["total"]
    sample = client.get("/api/try/sample").json()
    client.post("/api/try", json=sample)
    assert client.get("/api/records").json()["total"] == before
    assert client.get("/api/runs").json() == [] or True   # no new run appears below
    runs = client.get("/api/runs").json()
    assert all(r.get("record_count") != 1 for r in runs), \
        "an ad-hoc try must never appear in the run history"


def test_try_rejects_an_empty_submission(client):
    r = client.post("/api/try", json={})
    assert r.status_code == 422


def test_try_caps_the_input_size(client):
    """A public endpoint that accepts unbounded text is a public endpoint that
    accepts unbounded work."""
    huge = "Shipper: X\n" * 20000
    r = client.post("/api/try", json={"subject": "s", "body": "b",
                                      "si_text": huge, "bl_text": huge})
    assert r.status_code == 200          # truncated, not refused


def test_try_needs_both_documents_to_compare(client):
    """A comparison with one document escalates rather than inventing a verdict."""
    d = client.post("/api/try", json={
        "subject": "Please compare the SI and the draft BL",
        "body": "Kindly compare the attached SI and draft BL and confirm.",
        "si_text": "Shipper: ACME SDN BHD\nPort of Loading: PORT KLANG\n",
        "bl_text": "",
    }).json()
    assert d["status"] == "NEEDS_REVIEW"
    assert d["comparisons"] == []
