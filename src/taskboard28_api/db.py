"""Postgres access: connection per call, timeouts, self-applied schema, readiness."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import psycopg
import structlog

logger = structlog.get_logger(__name__)

SCHEMA_LOCK_KEY: Final = 2028_0001
TASKS_LIMIT_LOCK_KEY: Final = 2028_0002

CREATE_MIGRATIONS_SQL: Final = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""

CREATE_TASKS_SQL: Final = """
CREATE TABLE tasks (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         uuid NOT NULL UNIQUE,
    title      text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   date NULL,
    created_at timestamptz NOT NULL
)
"""

MIGRATIONS: Final[list[tuple[int, str]]] = [(1, CREATE_TASKS_SQL)]

_LOCK_SQL: Final = "SELECT pg_advisory_xact_lock(%s)"
_APPLIED_SQL: Final = "SELECT version FROM schema_migrations"
_RECORD_SQL: Final = "INSERT INTO schema_migrations (version) VALUES (%s)"

_schema_ready = False


class TaskStoreUnavailableError(Exception):
    """The database is unreachable, too slow or the connection was lost."""


def conninfo() -> str:
    """The libpq conninfo: DATABASE_URL, or "" so libpq falls back to PG* variables."""
    return os.environ.get("DATABASE_URL", "")


def _apply_migrations(conn: psycopg.Connection) -> None:
    """Apply pending migrations in one transaction under an advisory lock."""
    global _schema_ready
    with conn.transaction():
        conn.execute(CREATE_MIGRATIONS_SQL)
        conn.execute(_LOCK_SQL, (SCHEMA_LOCK_KEY,))
        applied = {row[0] for row in conn.execute(_APPLIED_SQL).fetchall()}
        for version, sql in MIGRATIONS:
            if version in applied:
                continue
            conn.execute(sql)
            conn.execute(_RECORD_SQL, (version,))
            logger.info("db_schema_applied", version=version)
    _schema_ready = True


@contextmanager
def connect(
    *, connect_timeout: int = 3, statement_timeout_ms: int = 5000
) -> Iterator[psycopg.Connection]:
    """Open a connection for one database call; commit on success, roll back on error."""
    try:
        conn = psycopg.connect(
            conninfo(),
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout_ms} -c TimeZone=UTC",
            application_name="taskboard28-api",
        )
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        logger.warning("task_store_unavailable", error=type(exc).__name__)
        raise TaskStoreUnavailableError from exc
    try:
        with conn:
            if not _schema_ready:
                _apply_migrations(conn)
            yield conn
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        logger.warning("task_store_unavailable", error=type(exc).__name__)
        raise TaskStoreUnavailableError from exc
    finally:
        conn.close()


def ensure_schema() -> None:
    """Apply pending migrations now (startup, test fixtures)."""
    with connect() as conn:
        _apply_migrations(conn)


def check_ready() -> bool:
    """True when the database answers SELECT 1 within 2 s; never raises."""
    try:
        with connect(connect_timeout=2, statement_timeout_ms=2000) as conn:
            conn.execute("SELECT 1")
    except TaskStoreUnavailableError:
        return False
    return True
