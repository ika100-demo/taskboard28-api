"""Acceptance tests for spec 002 (keep tasks in Postgres), against a real Postgres.

Fixtures `postgres_dsn`, `seed_tasks`, `empty_database` and the autouse `_tasks_db`
come from tests/conftest.py (plan task t1).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard28_api.main import app

UNAVAILABLE = {"detail": "task store unavailable"}
REFUSED_DSN = "postgresql://u:p@127.0.0.1:1/x"


def _locs(response: Any) -> list[list[Any]]:
    return [item["loc"] for item in response.json()["detail"]]


def test_ac_002_1_empty_database_starts_and_accepts_tasks(
    empty_database: None,
) -> None:  # AC-002.1
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 200
        r = client.post("/tasks", json={"title": "Buy milk"})
        assert r.status_code == 201
        assert r.json()["title"] == "Buy milk"


def test_ac_002_2_tasks_survive_restart() -> None:  # AC-002.2
    created = []
    with TestClient(app) as client:
        for title, due in [("A", "2026-12-24"), ("B", None), ("C", "2026-01-01")]:
            r = client.post("/tasks", json={"title": title, "due_date": due})
            assert r.status_code == 201
            created.append(r.json())
    with TestClient(app) as client:
        r = client.get("/tasks")
        assert r.status_code == 200
        assert r.json() == created
    from taskboard28_api.tasks import TaskStore

    assert [t.model_dump(mode="json") for t in TaskStore().list()] == created


def test_ac_002_3_due_dates_and_order() -> None:  # AC-002.3
    with TestClient(app) as client:
        a = client.post("/tasks", json={"title": "A", "due_date": "2026-12-24"})
        b = client.post("/tasks", json={"title": "B"})
        assert a.status_code == 201
        assert b.status_code == 201
        r = client.get("/tasks")
    assert r.status_code == 200
    body = r.json()
    assert [t["title"] for t in body] == ["A", "B"]
    assert body[0]["due_date"] == "2026-12-24"
    assert body[1]["due_date"] is None
    assert body[-1] == b.json()


def test_ac_002_4_empty_database_lists_empty_array() -> None:  # AC-002.4
    with TestClient(app) as client:
        r = client.get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"title": 42},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "  " + "x" * 201 + "  "},
    ],
)
def test_ac_002_5_invalid_title_is_422_and_not_stored(
    payload: dict[str, Any],
) -> None:  # AC-002.5
    with TestClient(app) as client:
        r = client.post("/tasks", json=payload)
        assert r.status_code == 422
        assert any(loc[-1] == "title" for loc in _locs(r))
        assert client.get("/tasks").json() == []


def test_ac_002_6_limit_of_1000_also_after_restart(
    seed_tasks: Callable[[int], None],
) -> None:  # AC-002.6
    seed_tasks(1000)
    with TestClient(app):
        pass
    with TestClient(app) as client:  # restarted against the same database
        r = client.post("/tasks", json={"title": "one too many"})
        assert r.status_code == 409
        assert r.json() == {"detail": "task limit of 1000 reached"}
        listed = client.get("/tasks")
        assert listed.status_code == 200
        assert len(listed.json()) == 1000


def test_ac_002_7_unreachable_database_is_503(
    monkeypatch: pytest.MonkeyPatch, postgres_dsn: str
) -> None:  # AC-002.7
    with TestClient(app) as client:
        monkeypatch.setenv("DATABASE_URL", REFUSED_DSN)
        g = client.get("/tasks")
        assert g.status_code == 503
        assert g.json() == UNAVAILABLE
        p = client.post("/tasks", json={"title": "lost"})
        assert p.status_code == 503
        assert p.json() == UNAVAILABLE
        assert client.get("/ready").status_code == 503
        assert client.get("/health").status_code == 200
        monkeypatch.setenv("DATABASE_URL", postgres_dsn)
        assert client.get("/tasks").json() == []


def test_ac_002_7_database_not_answering_is_503(postgres_dsn: str) -> None:  # AC-002.7
    import psycopg

    with TestClient(app) as client:
        lock_conn = psycopg.connect(postgres_dsn)
        try:
            lock_conn.execute("LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE")
            g = client.get("/tasks")
            assert g.status_code == 503
            assert g.json() == UNAVAILABLE
            p = client.post("/tasks", json={"title": "lost"})
            assert p.status_code == 503
            assert p.json() == UNAVAILABLE
            assert client.get("/health").status_code == 200
        finally:
            lock_conn.rollback()
            lock_conn.close()
        assert client.get("/tasks").json() == []


def test_ac_002_8_recovers_after_outage_without_restart(
    monkeypatch: pytest.MonkeyPatch, postgres_dsn: str
) -> None:  # AC-002.8
    with TestClient(app) as client:
        created = client.post("/tasks", json={"title": "before outage"})
        assert created.status_code == 201
        monkeypatch.setenv("DATABASE_URL", REFUSED_DSN)
        assert client.get("/tasks").status_code == 503
        assert client.get("/ready").status_code == 503
        monkeypatch.setenv("DATABASE_URL", postgres_dsn)
        r = client.get("/tasks")
        assert r.status_code == 200
        assert r.json() == [created.json()]
        assert client.get("/ready").status_code == 200
