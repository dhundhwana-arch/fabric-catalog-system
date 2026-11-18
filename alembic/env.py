"""Alembic environment.

Database URL resolution (never hard-coded in alembic.ini):

1. ``ALEMBIC_DATABASE_URL`` if set (used by the migration test-suite to
   point at a throwaway PostgreSQL/SQLite database);
2. otherwise the application's ``DATABASE_URL`` setting.

This means operators migrate whatever the application is configured to
use, and credentials stay in the environment/secret store.

``render_as_batch`` is enabled for SQLite: SQLite cannot ``ALTER TABLE``
most things, so Alembic rewrites the table (copy -> swap). That is what
makes the same migration script usable on both SQLite (dev) and PostgreSQL
(production).
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the application package importable when alembic runs from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import models  # noqa: F401,E402  (registers metadata)
from app.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.getenv("ALEMBIC_DATABASE_URL")
    if url:
        return url
    from app.config import get_settings

    return get_settings().database_url


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade head --sql``) for review/DBA."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_is_sqlite(url),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _database_url()
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(url),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
