"""Unit tests for task schemas and the Postgres-backed store."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date
from typing import Any

import pytest
from pydantic import ValidationError

from taskboard28_api.db import TaskStoreUnavailableError
from taskboard28_api.tasks import MAX_TASKS, TaskCreate, TaskLimitReachedError, TaskStore


def test_fresh_store_is_empty() -> None:
    assert TaskStore().list() == []


def test_add_and_order() -> None:
    store = TaskStore()
    a = store.add(TaskCreate(title="a"))
    b = store.add(TaskCreate(title="b", due_date="2026-12-24"))  # type: ignore[arg-type]
    assert [t.id for t in store.list()] == [a.id, b.id]
    assert a.due_date is None
    assert b.due_date == date(2026, 12, 24)
    assert a.created_at.tzinfo is UTC


def test_fresh_store_sees_earlier_tasks() -> None:
    a = TaskStore().add(TaskCreate(title="a"))
    assert TaskStore().list() == [a]


def test_limit_with_seeded_tasks(seed_tasks: Callable[[int], None]) -> None:
    seed_tasks(MAX_TASKS)
    store = TaskStore()
    with pytest.raises(TaskLimitReachedError):
        store.add(TaskCreate(title="x"))
    assert len(store.list()) == MAX_TASKS


def test_unreachable_database_raises_and_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, postgres_dsn: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")
    with pytest.raises(TaskStoreUnavailableError):
        TaskStore().add(TaskCreate(title="a"))
    monkeypatch.setenv("DATABASE_URL", postgres_dsn)
    assert TaskStore().list() == []


def test_list_returns_copy() -> None:
    store = TaskStore()
    store.add(TaskCreate(title="a"))
    store.list().clear()
    assert len(store.list()) == 1


def test_clear() -> None:
    store = TaskStore()
    store.add(TaskCreate(title="a"))
    store.clear()
    assert store.list() == []


def test_limit() -> None:
    store = TaskStore()
    for i in range(MAX_TASKS):
        store.add(TaskCreate(title=f"t{i}"))
    with pytest.raises(TaskLimitReachedError):
        store.add(TaskCreate(title="x"))
    assert len(store.list()) == MAX_TASKS


def test_title_trimmed_and_bounds() -> None:
    assert TaskCreate(title="  hi  ").title == "hi"
    assert len(TaskCreate(title="a" * 200).title) == 200
    assert len(TaskCreate(title=" " + "a" * 200 + " ").title) == 200


@pytest.mark.parametrize("title", ["", "   ", "a" * 201, 5, None])
def test_bad_title(title: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate(title=title)
    assert exc.value.errors()[0]["loc"] == ("title",)


def test_missing_title() -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate({})
    assert exc.value.errors()[0]["loc"] == ("title",)


@pytest.mark.parametrize(
    "value",
    ["2026-02-30", "20261224", "2026-12-24T00:00:00Z", "24.12.2026", 20261224],
)
def test_bad_due_date(value: Any) -> None:
    with pytest.raises(ValidationError) as exc:
        TaskCreate.model_validate({"title": "x", "due_date": value})
    assert exc.value.errors()[0]["loc"] == ("due_date",)


def test_null_due_date() -> None:
    assert TaskCreate.model_validate({"title": "x", "due_date": None}).due_date is None
