"""Alembic environment. Phase 13.

THE SCHEMA LIVES IN VERSION CONTROL. `Base.metadata.create_all` is used only by the
SQLite test repository; the PostgreSQL schema is owned by the migrations in
`alembic/versions/`, because a schema that two different mechanisms can create is a
schema that quietly differs between a developer's laptop and Azure.

The connection string comes from `DATABASE_URL` in the ENVIRONMENT, never from
`alembic.ini`. A password in a committed ini file is the oldest way to leak a
database, and this repository is public.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from shipdoc.adapters.db.models import Base  # noqa: E402
from shipdoc.adapters.db.sqlstore import _normalise_url  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set.\n"
            "  Alembic needs a database to migrate. Set it in your environment —\n"
            "  see .env.example — or skip migrations entirely: the system runs\n"
            "  without a database and writes files only.")
    return _normalise_url(url)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata,
                      literal_binds=True, compare_type=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
