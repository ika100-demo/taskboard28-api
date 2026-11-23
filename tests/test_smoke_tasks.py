"""Smoke tests for spec 001: reach the service only through SMOKE_BASE_URL."""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest


def _call(base: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.load(response)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_1_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    payload = {"title": title, "due_date": "2026-12-24"}
    status, body = _call(smoke_base_url, "POST", "/tasks", payload)
    assert status == 201
    assert isinstance(body["id"], str)
    assert body["id"]
    assert body["title"] == title
    assert body["due_date"] == "2026-12-24"
    assert datetime.fromisoformat(body["created_at"]).utcoffset() == timedelta(0)


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_ac_001_5_list_in_creation_order(smoke_base_url: str) -> None:  # AC-001.5
    titles = [f"smoke-{uuid.uuid4()}" for _ in range(3)]
    for title in titles:
        status, _ = _call(smoke_base_url, "POST", "/tasks", {"title": title})
        assert status == 201
    status, body = _call(smoke_base_url, "GET", "/tasks")
    assert status == 200
    listed = [t["title"] for t in body if t["title"] in titles]
    assert listed == titles


@pytest.mark.smoke
def test_smoke_ac_001_5_list_answers_with_array(smoke_base_url: str) -> None:  # AC-001.5
    status, body = _call(smoke_base_url, "GET", "/tasks")
    assert status == 200
    assert isinstance(body, list)
