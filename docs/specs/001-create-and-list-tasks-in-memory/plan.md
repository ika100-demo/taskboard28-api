---
spec_id: 001-create-and-list-tasks-in-memory
shape: service-python
spec_hash: cab7a19852ee
summary: POST /tasks and GET /tasks backed by a bounded, lock-guarded in-memory store
tasks:
  - id: t1
    title: Add task schemas and the in-memory TaskStore
    files: [src/taskboard28_api/tasks/__init__.py, src/taskboard28_api/tasks/schemas.py, src/taskboard28_api/tasks/store.py, tests/test_task_store.py]
    covers: [AC-001.2, AC-001.3, AC-001.4, AC-001.7, AC-001.8]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Expose POST /tasks and GET /tasks and wire the router into the app
    files: [src/taskboard28_api/tasks/api.py, src/taskboard28_api/tasks/__init__.py, src/taskboard28_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8]
    parallel_safe: false
    depends_on: [t1]
    done: true
human_steps:
  - Confirm the taskboard28-api entry in ika100-demo/taskboard28-gitops system.yaml runs a single replica (replicas 1), because tasks are held per process (spec A9)
---

# Plan — 001 Create and list tasks in memory

See [design.md](design.md) for the contract, the module signatures and how acceptance tests isolate the store.

## t1 — Add task schemas and the in-memory TaskStore

**Files:** src/taskboard28_api/tasks/__init__.py, src/taskboard28_api/tasks/schemas.py, src/taskboard28_api/tasks/store.py, tests/test_task_store.py
**Covers:** AC-001.2, AC-001.3, AC-001.4, AC-001.7, AC-001.8
**Goal:** the validation rules and the bounded store exist as plain Python, independent of HTTP, exactly as the design's Modules section specifies.

**Implementation notes:**
- `schemas.py`: `TaskCreate` with `extra="ignore"`; `title` as the strict, trimmed 1-200 `Annotated[str, StringConstraints(...)]`; `due_date: date | None = None` with a `mode="before"` validator: `None` passes, a non-string or a string not matching `^\d{4}-\d{2}-\d{2}$` or failing `date.fromisoformat` raises `ValueError` (so the error `loc` is `due_date`).
- `schemas.py`: `Task` response model (`id: str`, `title: str`, `due_date: date | None`, `created_at: datetime`), UTC-aware `created_at`.
- `store.py`: `MAX_TASKS: Final = 1000`, `TaskLimitReachedError`, `TaskStore` with `add`, `list` (returns a copy, creation order), `clear`; `add` checks the limit and appends under a `threading.Lock`, assigns `str(uuid4())` and `datetime.now(UTC)`.
- `__init__.py`: re-export `TaskCreate`, `Task`, `TaskStore`, `TaskLimitReachedError`, `MAX_TASKS`.
- `tests/test_task_store.py`: unit tests for the store (order, copy semantics, limit at 1000, a fresh instance is empty) and the schema edge cases (whitespace title, 200 vs 201 characters, `"2026-02-30"`, `"20261224"`, `"2026-12-24T00:00:00Z"`, integer title, integer due_date).

**Done when:** `tests/test_task_store.py` passes and `devbox run quality` is clean. The HTTP acceptance tests still fail (no route yet).

## t2 — Expose POST /tasks and GET /tasks and wire the router into the app

**Files:** src/taskboard28_api/tasks/api.py, src/taskboard28_api/tasks/__init__.py, src/taskboard28_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7, AC-001.8
**Goal:** the endpoints answer exactly as the design's Contract section states.

**Implementation notes:**
- `api.py`: module-level `_store = TaskStore()`, `get_task_store() -> TaskStore`, `router = APIRouter(tags=["tasks"])`.
- `POST /tasks` (`status_code=201`, `response_model=Task`): takes `TaskCreate` and `Depends(get_task_store)`; maps `TaskLimitReachedError` to `HTTPException(409, "task limit of 1000 reached")`.
- `GET /tasks` (`response_model=list[Task]`): returns `store.list()`.
- Sync handlers (`def`), matching the existing endpoints; the store's lock makes them threadpool-safe.
- `__init__.py`: also re-export `router` and `get_task_store`.
- `main.py`: `app.include_router(router)` after the middleware setup; nothing else changes.
- Log one structured event per create (`task_created`, `task_id`) and per limit hit (`task_limit_reached`) via structlog; never log the title.

**Done when:** the acceptance tests for AC-001.1 to AC-001.8 pass in-process, the existing tests (`test_health`, `test_metrics`, `test_contract`) still pass, and `devbox run ci` is green.
