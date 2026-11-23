"""HTTP endpoints for tasks."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from taskboard28_api import db
from taskboard28_api.tasks.schemas import Task, TaskCreate
from taskboard28_api.tasks.store import MAX_TASKS, TaskLimitReachedError, TaskStore

logger = structlog.get_logger(__name__)

_UNAVAILABLE = "task store unavailable"

_store = TaskStore()


def get_task_store() -> TaskStore:
    """Dependency returning the process-wide task store."""
    return _store


router = APIRouter(tags=["tasks"])

StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=Task)
def create_task(data: TaskCreate, store: StoreDep) -> Task:
    """Create a task."""
    try:
        task = store.add(data)
    except db.TaskStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc
    except TaskLimitReachedError as exc:
        logger.warning("task_limit_reached")
        raise HTTPException(status_code=409, detail=f"task limit of {MAX_TASKS} reached") from exc
    logger.info("task_created", task_id=task.id)
    return task


@router.get("/tasks", response_model=list[Task])
def list_tasks(store: StoreDep) -> list[Task]:
    """List all tasks."""
    try:
        return store.list()
    except db.TaskStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE) from exc
