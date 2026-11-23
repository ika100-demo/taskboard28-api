"""Postgres-backed task store."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from taskboard28_api import db
from taskboard28_api.tasks.schemas import Task, TaskCreate

MAX_TASKS: Final = 1000

_LOCK_SQL: Final = "SELECT pg_advisory_xact_lock(%s)"
_COUNT_SQL: Final = "SELECT count(*) FROM tasks"
_INSERT_SQL: Final = (
    "INSERT INTO tasks (id, title, due_date, created_at) VALUES (%s, %s, %s, %s) "
    "RETURNING id, title, due_date, created_at"
)
_LIST_SQL: Final = "SELECT id, title, due_date, created_at FROM tasks ORDER BY seq"
_CLEAR_SQL: Final = "TRUNCATE tasks"


class TaskLimitReachedError(Exception):
    """Raised when the store already holds MAX_TASKS tasks."""


def _row_to_task(row: tuple[Any, ...]) -> Task:
    return Task(
        id=str(row[0]),
        title=row[1],
        due_date=row[2],
        created_at=row[3].astimezone(UTC),
    )


class TaskStore:
    """Task storage in the Postgres `tasks` table; holds no state itself."""

    def add(self, data: TaskCreate) -> Task:
        with db.connect() as conn:
            conn.execute(_LOCK_SQL, (db.TASKS_LIMIT_LOCK_KEY,))
            count_row = conn.execute(_COUNT_SQL).fetchone()
            if count_row is not None and count_row[0] >= MAX_TASKS:
                raise TaskLimitReachedError(f"limit of {MAX_TASKS} tasks reached")
            row = conn.execute(
                _INSERT_SQL,
                (uuid4(), data.title, data.due_date, datetime.now(UTC)),
            ).fetchone()
        if row is None:
            raise RuntimeError("insert returned no row")
        return _row_to_task(row)

    def list(self) -> list[Task]:
        with db.connect() as conn:
            rows = conn.execute(_LIST_SQL).fetchall()
        return [_row_to_task(row) for row in rows]

    def clear(self) -> None:
        with db.connect() as conn:
            conn.execute(_CLEAR_SQL)
