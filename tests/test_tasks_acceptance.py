"""Acceptance tests for spec 001 (create and list tasks in memory)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard28_api.main import app


def _tasks_module() -> Any:
    try:
        import taskboard28_api.tasks as tasks
    except ImportError:
        pytest.fail("taskboard28_api.tasks is missing")
    return tasks


class _Env:
    def __init__(self) -> None:
        self.client = TestClient(app)
        self.store: Any = None

    def install_store(self) -> Any:
        tasks = _tasks_module()
        self.store = tasks.TaskStore()
        store = self.store
        app.dependency_overrides[tasks.get_task_store] = lambda: store
        return store


@pytest.fixture()
def env() -> Iterator[_Env]:
    e = _Env()
    try:
        tasks = __import__("taskboard28_api.tasks", fromlist=["x"])
    except ImportError:
        tasks = None
    if tasks is not None:
        e.install_store()
    try:
        yield e
    finally:
        if tasks is not None:
            app.dependency_overrides.pop(tasks.get_task_store, None)


def _locs(response: Any) -> list[list[Any]]:
    return [item["loc"] for item in response.json()["detail"]]


def _assert_utc_iso(value: str) -> None:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)


def test_ac_001_1_create_task_with_due_date(env: _Env) -> None:  # AC-001.1
    r = env.client.post("/tasks", json={"title": "Buy milk", "due_date": "2026-12-24"})
    assert r.status_code == 201
    body = r.json()
    assert isinstance(body["id"], str)
    assert body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-24"
    _assert_utc_iso(body["created_at"])


def test_ac_001_2_create_task_without_due_date(env: _Env) -> None:  # AC-001.2
    r = env.client.post("/tasks", json={"title": "No date"})
    assert r.status_code == 201
    assert r.json()["due_date"] is None
    r = env.client.post("/tasks", json={"title": "Null date", "due_date": None})
    assert r.status_code == 201
    assert r.json()["due_date"] is None


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
def test_ac_001_3_invalid_title_is_422(env: _Env, payload: dict[str, Any]) -> None:  # AC-001.3
    r = env.client.post("/tasks", json=payload)
    assert r.status_code == 422
    assert ["body", "title"] in _locs(r)
    listed = env.client.get("/tasks")
    assert listed.status_code == 200
    assert listed.json() == []


def test_ac_001_3_title_of_200_chars_after_trim_is_accepted(env: _Env) -> None:  # AC-001.3
    r = env.client.post("/tasks", json={"title": "  " + "x" * 200 + "  "})
    assert r.status_code == 201
    assert r.json()["title"] == "x" * 200


@pytest.mark.parametrize("due", ["24.12.2026", "2026-02-30", "2026-12-24T10:00:00Z"])
def test_ac_001_4_invalid_due_date_is_422(env: _Env, due: str) -> None:  # AC-001.4
    r = env.client.post("/tasks", json={"title": "Bad date", "due_date": due})
    assert r.status_code == 422
    assert ["body", "due_date"] in _locs(r)
    listed = env.client.get("/tasks")
    assert listed.status_code == 200
    assert listed.json() == []


def test_ac_001_5_list_in_creation_order(env: _Env) -> None:  # AC-001.5
    created = []
    for title, due in [("A", "2026-01-01"), ("B", None), ("C", "2026-03-03")]:
        r = env.client.post("/tasks", json={"title": title, "due_date": due})
        assert r.status_code == 201
        created.append(r.json())
    r = env.client.get("/tasks")
    assert r.status_code == 200
    assert r.json() == created
    assert [t["title"] for t in r.json()] == ["A", "B", "C"]


def test_ac_001_6_fresh_list_is_empty(env: _Env) -> None:  # AC-001.6
    r = env.client.get("/tasks")
    assert r.status_code == 200
    assert r.json() == []


def test_ac_001_8_limit_of_1000_tasks(env: _Env) -> None:  # AC-001.8
    for i in range(1000):
        r = env.client.post("/tasks", json={"title": f"t{i}"})
        assert r.status_code == 201
    r = env.client.post("/tasks", json={"title": "one too many"})
    assert r.status_code == 409
    assert r.json() == {"detail": "task limit of 1000 reached"}
    listed = env.client.get("/tasks")
    assert listed.status_code == 200
    assert len(listed.json()) == 1000
    assert re.fullmatch(r"t\d+", listed.json()[-1]["title"])
    assert listed.json()[-1]["title"] == "t999"
