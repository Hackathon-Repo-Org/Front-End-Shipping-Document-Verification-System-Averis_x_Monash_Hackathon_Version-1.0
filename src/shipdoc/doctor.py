"""`python -m shipdoc doctor` — one command that proves the install works.

Every FAIL line says what to DO, not just what is wrong.

AMENDMENT 1 (the lesson of the Phase 5 stale-hash bug): no check here may pass by
nothing happening. The pipeline check DELETES its output file first and then requires
it to be recreated — "the file is still there" is not evidence that anything ran.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def importlib_missing(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is None
    except (ImportError, ValueError):
        return True


MIN_PYTHON = (3, 12)
SAMPLE_SIZE = 10


class Result:
    __slots__ = ("name", "ok", "detail", "remedy", "optional")

    def __init__(self, name, ok, detail="", remedy="", optional=False):
        self.name, self.ok, self.detail = name, ok, detail
        self.remedy, self.optional = remedy, optional

    def line(self) -> str:
        mark = "ok  " if self.ok else ("--  " if self.optional else "FAIL")
        out = f"  [{mark}] {self.name:<24} {self.detail}"
        if not self.ok and self.remedy:
            out += f"\n         -> {self.remedy}"
        return out


def _check_python() -> Result:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PYTHON
    return Result("python version", ok, f"{v.major}.{v.minor}.{v.micro}",
                  f"shipdoc needs Python >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}. "
                  f"Install it and recreate the venv.")


def _check_import() -> Result:
    try:
        import shipdoc  # noqa: F401
        from shipdoc import pipeline  # noqa: F401
        return Result("package imports", True, "shipdoc, shipdoc.pipeline")
    except Exception as e:
        return Result("package imports", False, f"{type(e).__name__}: {e}",
                      'run  pip install -e "."  from the repo root')


def _check_corpus(root: Path) -> tuple[Result, Path | None]:
    ds = root / "dataset"
    inbox, att = ds / "inbox", ds / "attachments"
    n_i = len(list(inbox.glob("email_*.json"))) if inbox.is_dir() else 0
    n_a = len(list(att.iterdir())) if att.is_dir() else 0
    ok = n_i > 0 and n_a > 0
    return (Result("corpus", ok, f"{n_i} emails, {n_a} attachments",
                   f"expected dataset/inbox and dataset/attachments under {root}. "
                   f"Run doctor from the repo root."),
            ds if ok else None)


def _check_config(root: Path) -> tuple[Result, object | None]:
    try:
        from shipdoc.config import load_config
        cfg = load_config(root / "config")
    except Exception as e:
        return Result("config", False, f"{type(e).__name__}: {e}",
                      f"expected config/fields.yaml and config/pipeline.yaml "
                      f"under {root}"), None
    n = len(cfg.fields)
    ok = n == 7
    return (Result("config", ok, f"{n} compared fields defined",
                   "fields.yaml must define exactly the 7 compared fields; "
                   "see docs/spec/ARCHITECTURE_SPEC_V2.md M14"),
            cfg if ok else None)


def _check_tests(root: Path, run: bool) -> Result:
    if not run:
        return Result("test suite", True, "skipped (--fast)", optional=True)
    # Ask THIS interpreter, not the PATH: a pytest.exe belonging to some other
    # environment tells us nothing about whether `sys.executable -m pytest` will run.
    if importlib_missing("pytest"):
        # pytest is a [dev] extra, not core. A teammate on the tier-1 install has no
        # test runner, and that is fine — it must not read as a broken install.
        return Result("test suite", True, "pytest not installed (core install)",
                      'to run the tests:  pip install -e ".[dev]"', optional=True)
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=root, capture_output=True, text=True)
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    summary = tail[-1] if tail else "no output"
    return Result("test suite", proc.returncode == 0,
                  f"{summary}  ({time.time() - t0:.0f}s)",
                  "run  python -m pytest -q  and read the failures")


def _check_pipeline(root: Path, cfg, dataset: Path) -> tuple[Result, Path | None]:
    """Runs the pipeline on a small sample.

    The output file is DELETED first and must be recreated. A check that merely
    inspects a file which may not have been written is how Phase 5 concluded it had
    changed nothing when in fact the CLI had been failing for hours.
    """
    if cfg is None or dataset is None:
        return Result("pipeline (sample)", False, "skipped — corpus or config failed",
                      "fix the checks above first"), None
    try:
        from shipdoc.ingest.loader_port import LoaderInbox
        from shipdoc.pipeline import run_corpus, write_atomic

        out = Path(tempfile.mkdtemp(prefix="shipdoc-doctor-")) / "submission.json"
        out.unlink(missing_ok=True)
        assert not out.exists()

        class Sample:
            def __init__(self, inner, n):
                self._inner, self._n = inner, n

            def emails(self):
                return list(self._inner.emails())[: self._n]

            def read_bytes(self, p):
                return self._inner.read_bytes(p)

        inbox = Sample(LoaderInbox(str(dataset)), SAMPLE_SIZE)
        result = run_corpus(inbox, cfg, llm=None, decisions={},
                            cache_dir=out.parent / "cache")
        write_atomic(out, result["submission"])

        if not out.is_file():
            return Result("pipeline (sample)", False,
                          "ran but wrote no submission.json",
                          "this is a real bug — the run did not produce output"), None
        n = len(json.loads(out.read_text(encoding="utf-8")))
        return (Result("pipeline (sample)", n == SAMPLE_SIZE,
                       f"{n} records processed, submission.json written fresh",
                       "the sample run did not produce one entry per email"),
                out)
    except Exception as e:
        return Result("pipeline (sample)", False, f"{type(e).__name__}: {e}",
                      "run  python -m shipdoc --no-llm  and read the traceback"), None


def _check_schema(root: Path, produced: Path | None) -> Result:
    sample = root / "dataset" / "sample_submission.json"
    if produced is None or not sample.is_file():
        return Result("submission schema", False, "skipped — no output to validate",
                      "fix the pipeline check above")
    try:
        ours = json.loads(produced.read_text(encoding="utf-8"))
        ref = json.loads(sample.read_text(encoding="utf-8"))
        want = set(next(iter(ref.values())))
        bad = [k for k, v in ours.items() if set(v) != want]
        return Result("submission schema", not bad,
                      f"every entry has exactly {sorted(want)}",
                      f"these entries have the wrong keys: {bad[:5]}")
    except Exception as e:
        return Result("submission schema", False, f"{type(e).__name__}: {e}",
                      "submission.json is not valid JSON")


def run(root: Path | None = None, fast: bool = False) -> int:
    root = Path(root or Path.cwd())
    print("shipdoc doctor")
    print(f"  repo: {root}")
    print()

    results: list[Result] = [_check_python(), _check_import()]
    corpus, dataset = _check_corpus(root)
    results.append(corpus)
    config, cfg = _check_config(root)
    results.append(config)
    results.append(_check_tests(root, run=not fast))
    pipe, produced = _check_pipeline(root, cfg, dataset)
    results.append(pipe)
    results.append(_check_schema(root, produced))

    for r in results:
        print(r.line())

    print()
    print("  optional capabilities")
    try:
        from shipdoc.infra import capabilities as caps
        for c in caps.probe(cfg, root):
            if c.name in ("corpus", "rule extraction"):
                continue
            mark = "ok  " if c.ok else "--  "
            print(f"  [{mark}] {c.name:<24} {c.detail}")
            if not c.ok and c.remedy:
                print(f"         -> {c.remedy}")
    except Exception as e:
        print(f"  [--  ] capability probe failed: {e}")

    failed = [r for r in results if not r.ok and not r.optional]
    print()
    if failed:
        print(f"  RESULT: FAIL — {len(failed)} required check(s) failed")
        return 1
    print("  RESULT: PASS — shipdoc is ready")
    return 0
