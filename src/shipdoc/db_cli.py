"""M16c — `python -m shipdoc db ...`. Phase 13.

Three verbs and no more: `check` (is a database configured and reachable?), `seed`
(load the corpus, idempotently) and `counts` (row counts per table). Anything that
changes data beyond seeding belongs behind the API and a human, not behind a CLI verb
that is easy to run against the wrong environment.
"""
from __future__ import annotations

import sys


def run(action: str, *, source: str = "dataset") -> int:
    from shipdoc.adapters.db import build_repository, database_url

    url = database_url()
    if not url:
        print("shipdoc: no DATABASE_URL set, so no database is configured.")
        print("  This is a supported mode, not an error: the system runs and writes")
        print("  files to output/. See .env.example and SETUP.md tier 4.")
        return 0 if action == "check" else 2

    try:
        repo = build_repository(url)
    except ImportError:
        print("shipdoc: DATABASE_URL is set but the database extra is not installed.")
        print('  pip install -e ".[db]"')
        return 2
    except Exception as e:
        # Never echo the URL: it carries the password.
        print(f"shipdoc: could not connect to the database ({type(e).__name__}).")
        print("  Check the host, the credentials, and — on Azure — that the")
        print("  firewall allows this machine's outbound IP. See SETUP.md tier 4.")
        return 2

    if action == "check":
        counts = repo.counts()
        print("database reachable.")
        for t, n in counts.items():
            print(f"  {t:20} {n:>8}")
        return 0

    if action == "seed":
        from shipdoc.adapters.db.seed import seed_corpus
        seed_corpus(repo, source)
        return 0

    if action == "counts":
        for t, n in repo.counts().items():
            print(f"  {t:20} {n:>8}")
        return 0

    print(f"shipdoc: unknown db action {action!r}; use check, seed or counts",
          file=sys.stderr)
    return 2
