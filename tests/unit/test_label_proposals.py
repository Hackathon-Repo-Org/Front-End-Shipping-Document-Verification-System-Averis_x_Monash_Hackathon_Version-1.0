"""Phase 11 — detection, proposal and the boundary between them.

The invariant that matters most in this file is negative: there is no code path
anywhere in `src/shipdoc/` that writes an approval. `test_nothing_can_self_approve`
asserts it against the source, not against a comment.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from shipdoc.normalise.unknown import find_unknown, is_candidate
from shipdoc.review.proposals import (
    NONE,
    Proposal,
    already_known,
    read_proposals,
    write_proposals,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "shipdoc"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cfg():
    from shipdoc.config import load_config
    return load_config(ROOT / "config")


# ---------------------------------------------------------------- DETECTION

@pytest.mark.parametrize("line", [
    "Containers: 3 x 40'HC",
    "TOTAL GROSS WEIGHT: 23,702 KG",
    "Shipper | ACME TRADING SDN BHD",
    "Vessel Name: MAERSK KOWLOON",
])
def test_label_shaped_lines_are_candidates(line):
    assert is_candidate(line) is not None


@pytest.mark.parametrize("line,why", [
    ("", "blank"),
    ("BILL OF LADING", "a heading — nothing follows it"),
    ("PLO 22, PARIT RAJA INDUSTRIAL ESTATE, 86400 BATU PAHAT", "an address line"),
    ("Please compare the attached SI and draft BL: we need it before cut-off "
     "because the vessel sails on Friday and the shipper is waiting", "prose"),
    ("Date: 2026-09-20", "document furniture, not a compared field"),
    ("Page: 1 of 3", "footer boilerplate"),
    ("12345: something", "starts with a digit"),
    ("A: b", "too short to be a label"),
])
def test_non_labels_are_not_candidates(line, why):
    assert is_candidate(line) is None, why


def test_detection_has_no_frequency_threshold(cfg):
    """Structure, not proportion — a label seen ONCE is a candidate.

    A frequency threshold would mean the first N documents carrying a new label are
    silently mis-extracted while a counter warms up, which is exactly the failure
    Phase 10 Fix 1 exists to prevent.

    Asserted behaviourally: the same label yields a finding whether it appears once
    or many times, and detection carries no state between calls. An earlier version
    of this test grepped the module source and failed on the word "frequency" in its
    own docstring — which measured the prose, not the code.
    """
    from shipdoc.normalise.labels import LabelIndex
    index = LabelIndex(cfg)

    once = find_unknown("Shipper: ACME LTD\nWidget Count: 12\n", index, "a.txt", "BL")
    assert [u.normalised for u in once] == ["widget count"]

    many = "Shipper: ACME LTD\n" + "".join(
        f"Widget Count: {i}\n" for i in range(20))
    repeated = find_unknown(many, index, "b.txt", "BL")
    # Same finding, and reported ONCE per document however often it occurs.
    assert [u.normalised for u in repeated] == ["widget count"]


def test_known_and_anti_synonym_labels_are_not_reported(cfg):
    """`NET WEIGHT` is not an unknown label — it is a known one we refuse.

    Surfacing it as a discovery would put a question in front of a reviewer that the
    config already answers.
    """
    from shipdoc.normalise.labels import LabelIndex
    text = ("Shipper: ACME LTD\n"
            "NET WEIGHT: 45,120.00 KGS\n"
            "Widget Count: 12\n")
    found = {u.normalised for u in find_unknown(text, LabelIndex(cfg), "d.txt", "BL")}
    assert "net weight" not in found
    assert "shipper" not in found
    assert "widget count" in found


def test_every_unknown_carries_evidence(cfg):
    from shipdoc.normalise.labels import LabelIndex
    text = "Shipper: ACME LTD\nWidget Count: 12\nConsignee: BETA GMBH\n"
    for u in find_unknown(text, LabelIndex(cfg), "d.txt", "BL"):
        assert u.doc_ref and u.line_no > 0 and u.context.strip() and u.value


# ----------------------------------------------------------------- PROPOSAL

class _Model:
    """Records what it was asked and returns a scripted sequence."""

    model = "test-model"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt, *, choices=None, timeout_s=30.0):
        self.prompts.append(prompt)
        return self.answers.pop(0) if self.answers else "NONE"


def _unknown(label="Widget Count"):
    from shipdoc.types import UnknownLabel
    return UnknownLabel(raw=label, normalised=label.lower(), value="12",
                        doc_ref="d.txt", line_no=4, role="BL",
                        context="Shipper: ACME\nWidget Count: 12")


def test_free_text_is_never_accepted(cfg):
    """Same rule as M07: the answer is one of the seven names or NONE."""
    from shipdoc.llm.label_proposer import propose
    m = _Model("I think this is probably the container count!", "still not a field name")
    assert propose(_unknown(), cfg, m) is None
    assert len(m.prompts) == 2, "must retry exactly once, then give up"


def test_one_retry_then_success_is_accepted(cfg):
    from shipdoc.llm.label_proposer import propose
    m = _Model("gibberish", "container_count")
    p = propose(_unknown(), cfg, m)
    assert p is not None and p.proposed_field == "container_count"


def test_none_is_not_queued(cfg):
    """Asking a human to confirm that `Vessel:` is not one of our fields is waste."""
    from shipdoc.llm.label_proposer import propose
    assert propose(_unknown("Vessel"), cfg, _Model(NONE)) is None


def test_anti_synonym_is_auto_rejected_without_a_model_call(cfg):
    """`NET WEIGHT` must never reach a reviewer as a gross_weight_kg candidate."""
    from shipdoc.llm.label_proposer import propose
    m = _Model("gross_weight_kg")
    assert propose(_unknown("NET WEIGHT"), cfg, m) is None
    assert m.prompts == [], "the config already knows; do not spend a model call"


def test_no_model_means_no_proposal(cfg):
    from shipdoc.llm.label_proposer import propose
    assert propose(_unknown(), cfg, None) is None


# -------------------------------------------------------------------- QUEUE

def test_a_proposal_without_evidence_is_not_emitted(tmp_path):
    """Asking someone to rule on a label with no document is asking them to guess."""
    good = Proposal(normalised="a", label="A:", proposed_field="container_count",
                    model="m", prompt_version="v", doc_ref="d.txt", line_no=3,
                    role="BL", value="1", context="A: 1")
    blind = Proposal(normalised="b", label="B:", proposed_field="container_count",
                     model="m", prompt_version="v", doc_ref="", line_no=0,
                     role="BL", value="", context="")
    path = tmp_path / "q.json"
    assert write_proposals(path, [good, blind]) == 1
    assert [p.normalised for p in read_proposals(path)] == ["a"]


def test_one_label_one_proposal_once_ever(tmp_path):
    pending = [Proposal(normalised="containers", label="Containers:",
                        proposed_field="container_count", model="m",
                        prompt_version="v", doc_ref="d.txt", line_no=1,
                        role="BL", value="1", context="x")]

    class _V:
        entries = ()

    assert already_known("containers", _V(), pending) is True
    assert already_known("something else", _V(), pending) is False


# ------------------------------------------------------- THE HUMAN IN A LOOP

def test_nothing_can_self_approve():
    """No module under src/shipdoc/ may write an approval except the human-driven CLI.

    Asserted against the SOURCE with `ast`, not against a promise in a docstring. A
    proposal that applies itself is the failure mode this whole design exists to
    prevent, and it would arrive as a convenience flag.
    """
    writer = SRC / "labels_cli.py"
    writes = ("write_text", "write_bytes", "safe_dump", "dump")
    offenders = []

    for path in SRC.rglob("*.py"):
        if path == writer:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))

        # Does this module know the learned file by name, other than in prose?
        docstrings = {
            n.body[0].value
            for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
            and isinstance(n.body[0].value.value, str)
        }
        # The literal filename, in code rather than prose...
        names_file = any(
            isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "learned_labels.yaml" in n.value and n not in docstrings
            for n in ast.walk(tree))
        # ...or the FILENAME constant, which is how labels_cli actually reaches it.
        # Without this half, a new module could import FILENAME and write freely.
        names_file = names_file or any(
            isinstance(n, ast.ImportFrom) and n.module == "shipdoc.learned"
            and any(a.name == "FILENAME" for a in n.names)
            for n in ast.walk(tree))
        if not names_file:
            continue

        # ...and if so, does it also write to disk?
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in writes):
                offenders.append(f"{path.name}: calls {node.func.attr}()")

    assert not offenders, (
        "only labels_cli.py, driven by a human, may WRITE the learned vocabulary; "
        "reading it is fine. Offenders: " + "; ".join(sorted(set(offenders))))


def test_the_cli_offers_no_bulk_or_automatic_approval():
    """No --all, no --auto, no confidence threshold. The convenience IS the risk."""
    source = (SRC / "labels_cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = ("--all", "--auto", "--yes", "--approve-all", "--threshold",
              "--confidence")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in banned, f"{node.value} is a self-approval path"
