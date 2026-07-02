"""Alembic environment for the review gateway.

URL comes from gateway.config.settings (env-overridable: GWREV_DB_URL) so the
same migrations run on the dev SQLite DB and on a prod Postgres. SQLite gets
batch mode (render_as_batch) so future ALTERs work — SQLite can't ALTER in
place."""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Make `gateway` importable when alembic runs from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gateway import models  # noqa: E402,F401 — registers all tables on Base
from gateway.config import settings  # noqa: E402
from gateway.db import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        pass

target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or settings.db_url


def run_migrations_offline() -> None:
    url = _url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    connectable = create_engine(url, poolclass=pool.NullPool, future=True)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
