"""Shared pytest fixtures."""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable, Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from taskboard28_api.main import app

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tasks (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id         uuid NOT NULL UNIQUE,
    title      text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   date NULL,
    created_at timestamptz NOT NULL
);
INSERT INTO schema_migrations (version) VALUES (1) ON CONFLICT DO NOTHING;
"""


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    """DSN of the test database: TEST_DATABASE_URL or a postgres:16-alpine container."""
    url = os.environ.get("TEST_DATABASE_URL")
    previous = os.environ.get("DATABASE_URL")
    container = None
    if url:
        dsn = url
    else:
        from testcontainers.postgres import PostgresContainer

        container = PostgresContainer("postgres:16-alpine", driver=None)
        container.start()
        dsn = container.get_connection_url()
    os.environ["DATABASE_URL"] = dsn
    try:
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        if container is not None:
            container.stop()


@pytest.fixture(autouse=True)
def _tasks_db(request: pytest.FixtureRequest) -> None:
    """Start every non-smoke test with an empty, migrated database."""
    if request.node.get_closest_marker("smoke"):
        return
    dsn = request.getfixturevalue("postgres_dsn")
    try:
        db = importlib.import_module("taskboard28_api.db")
    except ImportError:
        db = None
    if db is not None:
        db.ensure_schema()
    with psycopg.connect(dsn, autocommit=True) as conn:
        if db is None:
            # Until db.py exists: apply the design's "Data" SQL directly.
            conn.execute(_SCHEMA_SQL)
        conn.execute("TRUNCATE tasks")


@pytest.fixture()
def seed_tasks(postgres_dsn: str) -> Callable[[int], None]:
    """Insert n valid tasks in one statement, in creation order."""

    def _seed(n: int) -> None:
        with psycopg.connect(postgres_dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, due_date, created_at) "
                "SELECT gen_random_uuid(), 'seed-' || i, NULL, "
                "now() + i * interval '1 millisecond' "
                "FROM generate_series(1, %s) AS i",
                (n,),
            )

    return _seed


@pytest.fixture()
def empty_database(postgres_dsn: str) -> None:
    """Drop tasks and schema_migrations so the database is as new."""
    with psycopg.connect(postgres_dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS tasks")
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
