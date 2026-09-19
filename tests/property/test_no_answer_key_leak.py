"""The answer key is a MEASURING INSTRUMENT, not an input.

The organisers permit using `ground_truth.json` for self-evaluation. That permission
is narrow, and this test is what keeps it narrow:

  - an evaluator OUTSIDE src/shipdoc/ may read it
  - NO module under src/shipdoc/ may read it, import the evaluator, or reference any
    email_id as a literal in a branch, dict key or rule

This test is why the team can move fast without cheating by accident. It FAILS if
someone adds the import.
"""
import ast
import re
from pathlib import Path

import pytest

from conftest import ROOT

SRC = ROOT / "src" / "shipdoc"
EVAL = ROOT / "eval"

# `email_001` etc. Any literal record id hard-coded into the package is a rule keyed
# to a specific answer, which is memorising rather than classifying.
EMAIL_ID_LITERAL = re.compile(r"""["']email_\d{3}["']""")

# What identifies the ANSWER KEY specifically. `sdoc-server` is deliberately NOT here:
# that directory holds the scoring server as well, and a help string telling a
# teammate where to run `docker compose up` is not a route to the labels. The markers
# below only match the key itself and the organisers' private data directory.
ANSWER_KEY_MARKERS = ("ground_truth", "ground-truth", "data_v2")


def source_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


# --------------------------------------------------------------------------
# Half 1 — src/shipdoc must not reach the answer key
# --------------------------------------------------------------------------

def string_literals(tree: ast.AST) -> list[str]:
    """Every string CONSTANT in the module, docstrings excluded.

    Checked at AST level rather than over raw text, for the same reason the layering
    test is: a comment explaining why there is no path here cannot become a path. A
    literal is what actually opens a file.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings]


@pytest.mark.parametrize("path", source_files(SRC), ids=lambda p: p.name)
def test_package_never_references_the_answer_key(path):
    literals = string_literals(ast.parse(path.read_text(encoding="utf-8")))
    hits = sorted({m for s in literals for m in ANSWER_KEY_MARKERS if m in s})
    assert not hits, (
        f"{path.relative_to(ROOT)} has a string literal naming {hits} — the pipeline "
        f"must never read or name the answer key. Measuring belongs in eval/.")


@pytest.mark.parametrize("path", source_files(SRC), ids=lambda p: p.name)
def test_package_never_hardcodes_an_email_id(path):
    """A rule keyed to a specific record is memorising the answers.

    Note this is deliberately stricter than the answer-key check: it catches
    `if rec.email_id == "email_507"` even though that reads no gold file at all.
    """
    found = EMAIL_ID_LITERAL.findall(path.read_text(encoding="utf-8"))
    assert not found, (
        f"{path.relative_to(ROOT)} hard-codes {sorted(set(found))}. Pipeline logic "
        f"must generalise; put record-specific expectations in tests/golden/.")


@pytest.mark.parametrize("path", source_files(SRC), ids=lambda p: p.name)
def test_package_never_imports_the_evaluator(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] == "eval"]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in ("eval", "evaluate"):
                bad.append(node.module)
    assert not bad, f"{path.relative_to(ROOT)} imports the evaluator: {bad}"


def test_the_package_does_not_ship_an_eval_module():
    """`eval/` is top-level and outside the package, so `pip install -e .` cannot
    put it on the path as part of shipdoc."""
    assert not (SRC / "eval").exists()
    assert not (SRC / "evaluate.py").exists()


# --------------------------------------------------------------------------
# Half 2 — the evaluator exists, is outside the package, and does read the key
# --------------------------------------------------------------------------

def test_the_evaluator_lives_outside_the_package():
    assert (EVAL / "evaluate.py").is_file()
    assert EVAL.resolve() != SRC.resolve()
    assert SRC.resolve() not in EVAL.resolve().parents


def test_the_evaluator_reads_the_answer_key():
    """The other half of the rule: measuring IS allowed, in this one place."""
    text = (EVAL / "evaluate.py").read_text(encoding="utf-8")
    assert "ground_truth" in text


def test_the_evaluator_imports_the_organisers_scoring():
    """A reimplementation that disagrees with theirs is worse than no evaluator."""
    text = (EVAL / "evaluate.py").read_text(encoding="utf-8")
    assert "scoring.py" in text and "spec_from_file_location" in text
    assert "def score_all" not in text, "do not reimplement the organisers' scoring"
