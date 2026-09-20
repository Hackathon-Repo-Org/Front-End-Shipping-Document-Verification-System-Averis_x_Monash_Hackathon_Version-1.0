"""Phase 13 — the database adapter.

RULE R1: THE DATABASE IS AN ADAPTER. Nothing under `ingest/`, `detect/`, `extract/`,
`route/`, `normalise/`, `compare/`, `state/` or `classify/` may import this package.
`tests/property/test_layering.py` enforces it, and
`tests/property/test_db_is_optional.py` proves a run with no `DATABASE_URL` is
byte-identical to one on a machine where these packages are not installed at all.

Nothing here is imported at module scope by the pipeline: `sqlalchemy` is an OPTIONAL
dependency, and `import shipdoc` must keep working without it.
"""
from __future__ import annotations

__all__ = ["RecordFilter", "RunInput", "build_repository", "database_url"]


def __getattr__(name: str):
    """Lazy re-export, so importing this package never costs a SQLAlchemy import."""
    if name in __all__:
        from shipdoc.adapters.db import repository
        return getattr(repository, name)
    raise AttributeError(name)
