"""Request and response models for tasks."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskCreate(BaseModel):
    """Payload to create a task; unknown fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    title: Annotated[
        str,
        StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200),
    ]
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _check_due_date(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not _DATE_RE.match(value):
            raise ValueError("due_date must be a YYYY-MM-DD calendar date")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a YYYY-MM-DD calendar date") from exc


class Task(BaseModel):
    """A stored task."""

    id: str
    title: str
    due_date: date | None
    created_at: datetime
