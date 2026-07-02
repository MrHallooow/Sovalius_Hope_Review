"""SQLAlchemy engine/session for the review gateway. SQLite in dev (zero
infra), Postgres in prod via GWREV_DB_URL — same models, no code change."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_connect_args = (
    {"check_same_thread": False} if settings.db_url.startswith("sqlite") else {}
)
engine = create_engine(settings.db_url, connect_args=_connect_args, future=True)


# SQLite has a single writer; WAL lets a reader and a writer coexist, and
# busy_timeout makes a writer wait (up to 5s) for the lock instead of raising
# "database is locked" immediately. No-op on Postgres (real row locking).
#
# ALSO: the stdlib sqlite3 driver only auto-BEGINs on DML, so a SAVEPOINT
# issued outside an explicit transaction opens its own transaction and the
# closing RELEASE SAVEPOINT *commits* it — which would silently break
# audit.record()'s stage-don't-commit contract (the audit row must commit in
# the SAME transaction as the action it records). The documented SQLAlchemy
# recipe below disables pysqlite's implicit BEGIN and emits it explicitly at
# transaction start, giving SQLite real savepoint semantics.
if settings.db_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - thin glue
        # Let SQLAlchemy (not pysqlite) control transaction scope.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _sqlite_begin(conn):  # pragma: no cover - thin glue
        conn.exec_driver_sql("BEGIN")


SessionLocal = sessionmaker(
    bind=engine, autoflush=False, expire_on_commit=False, future=True
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Bring the schema to head via Alembic — the single source of truth for the
    schema on both dev SQLite and prod Postgres. Run on startup so a fresh DB is
    migrated automatically; ``python -m alembic -c gateway/alembic.ini upgrade
    head`` does the same from the CLI for controlled deploys."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parent / "migrations")
    )
    cfg.set_main_option("sqlalchemy.url", settings.db_url)
    command.upgrade(cfg, "head")
