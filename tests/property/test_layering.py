"""The dependency rule, as a test rather than a document.

`adapters -> state -> compare -> normalise -> route -> extract -> detect -> ingest
-> types`. Nothing imports leftward, which in the ordering below means: no module may
import a layer that appears LATER in LAYER_ORDER than its own.

This is what stops the next person quietly breaking the architecture. It costs one
file, and it is parsed with `ast` rather than grepped — a regex over source text would
miss conditional imports and would fire on the word "adapters" inside a comment.
"""
import ast
from pathlib import Path

import pytest

from conftest import ROOT

SRC = ROOT / "src" / "shipdoc"

# Bottom first. Everything in FOUNDATION is importable by anyone.
#
# CHANGING THIS LIST MEANS CHANGING THE ARCHITECTURE. If you add, remove or reorder a
# layer here, update the dependency chain in docs/spec/ARCHITECTURE_SPEC_V2.md §3 in
# the same commit — the spec and this list are two statements of one rule, and a
# silent divergence between them is how the rule stops meaning anything.
FOUNDATION = ["types", "errors", "config", "infra"]

LAYER_ORDER = FOUNDATION + [
    # `classify` is absent from the chain written in v2 §3. It imports nothing but
    # foundation (types, errors) and its own submodules, so it sits here — low, and
    # first in the pipeline's order of operations. Placed deliberately rather than
    # left unchecked; see test_the_layer_list_covers_every_package.
    "classify",
    "ingest", "detect", "extract", "route",
    "normalise", "compare", "state", "review",
    "llm", "adapters",
]

# Leftward imports that exist and are not yet fixed. EMPTY as of Phase 4: the one
# entry (route/confirm.py -> normalise) was closed by making LabelIndex injection
# mandatory, with the orchestrator owning construction.
#
# Keep it empty. An entry here is architectural debt with a deadline, not a licence.
KNOWN_VIOLATIONS: set[tuple[str, str]] = set()

# These sit ABOVE the stack and may import freely.
#   pipeline/cli/__main__ — orchestration, explicitly exempted by M13
#   ui                    — reserved for a future dashboard. A UI reads records, the
#                           queue and the config at once, so it cannot sit inside the
#                           package without breaking this rule; it belongs above it.
EXEMPT = {"pipeline", "cli", "__main__", "ui"}

RANK = {name: i for i, name in enumerate(LAYER_ORDER)}


def layer_of(path: Path) -> str | None:
    """The layer a source file belongs to, or None if it is exempt/unclassified."""
    rel = path.relative_to(SRC)
    head = rel.parts[0]
    if head.endswith(".py"):
        stem = head[:-3]
        return stem if stem in RANK else None      # top-level module: types.py, cli.py…
    return head if head in RANK else None


def imported_layers(tree: ast.AST) -> set[str]:
    """Every shipdoc layer this module imports, from the parsed AST.

    DECISION (Phase 4): a `TYPE_CHECKING`-guarded import COUNTS AS A VIOLATION.
    `ast.walk` descends into `if TYPE_CHECKING:` bodies, so such imports are found
    here deliberately and are not special-cased anywhere below.

    The reason is that the rule protects the architecture, not the runtime. A
    TYPE_CHECKING import is still a textual dependency on a higher layer, and it is
    one keystroke — deleting the guard — from becoming a real one. A module that
    genuinely needs a type from above should declare the shape it requires locally,
    as `route/confirm.py:LabelMatcher` now does.
    """
    found: set[str] = set()

    def record(dotted: str | None) -> None:
        if not dotted:
            return
        parts = dotted.split(".")
        if parts[0] != "shipdoc" or len(parts) < 2:
            return
        if parts[1] in RANK:
            found.add(parts[1])

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                record(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # relative import — not used in this package
                continue
            record(node.module)
    return found


def source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py")
                  if "__pycache__" not in p.parts and p.name != "__init__.py")


def test_the_layer_list_covers_every_package():
    """A new subpackage must be placed in the ordering deliberately, not ignored."""
    packages = {p.name for p in SRC.iterdir()
                if p.is_dir() and p.name != "__pycache__"}
    unplaced = packages - set(RANK) - EXEMPT
    assert not unplaced, (
        f"these packages are not in LAYER_ORDER: {sorted(unplaced)}. "
        f"Add them at the right depth rather than leaving them unchecked.")


@pytest.mark.parametrize("path", source_files(), ids=lambda p: str(p.name))
def test_no_module_imports_leftward(path):
    """No module may import a layer above its own."""
    if path.stem in EXEMPT:
        return
    own = layer_of(path)
    if own is None:
        return

    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(SRC).as_posix()
    found = {
        target for target in imported_layers(tree)
        if RANK[target] > RANK[own] and target not in FOUNDATION
    }
    known = {t for (f, t) in KNOWN_VIOLATIONS if f == rel}

    new = found - known
    assert not new, (
        f"{path.relative_to(ROOT)} is in layer '{own}' (rank {RANK[own]}) but imports "
        f"{sorted(new)} — which sit above it. Arrows point inward only.")

    # A fixed violation must be struck from KNOWN_VIOLATIONS, or the list rots into a
    # permanent excuse and stops meaning anything.
    stale = known - found
    assert not stale, (
        f"{rel} no longer imports {sorted(stale)} — remove it from KNOWN_VIOLATIONS.")


def test_type_checking_imports_are_not_a_loophole():
    """Pins the Phase 4 decision so nobody re-opens it by accident.

    Synthesises a module that imports upward under `if TYPE_CHECKING:` and asserts
    the detector still sees it. If someone later makes `imported_layers` skip guarded
    imports, this fails and they have to argue the case rather than slip it through.
    """
    src = (
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from shipdoc.normalise.labels import LabelIndex\n"
    )
    assert "normalise" in imported_layers(ast.parse(src))


def test_route_does_not_depend_on_normalise():
    """The specific violation closed in Phase 4, pinned as its own named test.

    route/ sits below normalise/ in v2 §3. It needs label matching, so it declares
    the shape it requires (`LabelMatcher`) and the orchestrator injects an instance.
    Checked at AST level: prose in a docstring explaining WHY there is no import is
    fine and is what stops the next person re-adding one.
    """
    offenders = []
    for path in source_files():
        if path.relative_to(SRC).parts[0] != "route":
            continue
        imported = imported_layers(ast.parse(path.read_text(encoding="utf-8")))
        if "normalise" in imported:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"route/ imports normalise again: {offenders}"


def test_types_imports_nothing_from_the_package():
    """M02: types.py is the bottom. It may not import any other shipdoc module."""
    tree = ast.parse((SRC / "types.py").read_text(encoding="utf-8"))
    assert imported_layers(tree) == set()


def test_foundation_modules_do_not_import_upward():
    """types/errors/config/infra are importable by anyone, so they must depend on
    nothing but each other — otherwise the bottom of the stack drags the top in."""
    for name in FOUNDATION:
        for path in (p for p in source_files() if layer_of(p) == name):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            outside = imported_layers(tree) - set(FOUNDATION)
            assert not outside, (
                f"{path.relative_to(ROOT)} is foundation but imports {sorted(outside)}")


def test_external_schema_strings_stay_in_adapters():
    """I5, as narrowed in v2: status values, review_reason values and submission key
    names appear only in adapters/. Checked here so the rule travels with the layering
    test rather than living only in a CI grep."""
    import re
    banned = re.compile(
        r'"(OK|MISMATCH|NEEDS_REVIEW|missing_attachment|wrong_doc_type|unreadable'
        r'|missing_value)"')
    offenders = []
    for path in source_files():
        if path.relative_to(SRC).parts[0] == "adapters":
            continue
        if banned.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"external vocabulary outside adapters/: {offenders}"
