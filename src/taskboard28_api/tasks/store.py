"""In-memory task store."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Final
from uuid import uuid4

from taskboard28_api.tasks.schemas import Task, TaskCreate

MAX_TASKS: Final = 1000


class TaskLimitReachedError(Exception):
    """Raised when the store already holds MAX_TASKS tasks."""


class TaskStore:
    """Thread-safe, process-local task storage."""

    def __init__(self) -> None:
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, data: TaskCreate) -> Task:
        with self._lock:
            if len(self._tasks) >= MAX_TASKS:
                raise TaskLimitReachedError(f"limit of {MAX_TASKS} tasks reached")
            task = Task(
                id=str(uuid4()),
                title=data.title,
                due_date=data.due_date,
                created_at=datetime.now(UTC),
            )
            self._tasks.append(task)
            return task

    def list(self) -> list[Task]:
        with self._lock:
            return self._tasks.copy()

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
