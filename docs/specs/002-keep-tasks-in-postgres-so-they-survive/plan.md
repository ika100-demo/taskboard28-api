---
spec_id: 002-keep-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: 35a8e3a6e42f
summary: Tasks stored in Postgres via psycopg 3 (connection per call, self-applied schema), 503 and a database-aware /ready during outages
tasks:
  - id: t1
    title: Add the db module (conninfo, timeouts, migrations, readiness)
    files: [src/taskboard28_api/db.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.7, AC-002.8]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Back TaskStore with Postgres
    files: [src/taskboard28_api/tasks/store.py, tests/test_task_store.py]
    covers: [AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7]
    parallel_safe: true
    depends_on: [t1]
  - id: t3
    title: Answer 503 on store outages, apply the schema at startup, make /ready check the database
    files: [src/taskboard28_api/tasks/api.py, src/taskboard28_api/main.py]
    covers: [AC-002.1, AC-002.7, AC-002.8]
    parallel_safe: true
    depends_on: [t1]
  - id: t4
    title: Map 422 validation errors to the contract's title-required, title-min and title-max types
    files: [src/taskboard28_api/tasks/schemas.py, src/taskboard28_api/tasks/api.py, src/taskboard28_api/main.py]
    covers: []
    parallel_safe: false
    depends_on: [t3]
---

# Plan — 002 Keep tasks in Postgres so they survive restarts

See [design.md](design.md) for the decisions, signatures, schema, contract and the test fixtures. No gitops task: the system plan wires `uses: postgres` (`DATABASE_URL`, `PG*`) for this component.

## t1 — Add the db module (conninfo, timeouts, migrations, readiness)

**Files:** src/taskboard28_api/db.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.7, AC-002.8
**Goal:** one module owns every database connection with the spec's timeouts and error mapping and applies the schema itself. The Postgres test fixtures (`tests/conftest.py`) and the `psycopg` / `testcontainers` dependencies (`pyproject.toml`, `uv.lock`) are delivered by the red-tests step, not by this task.

**Implementation notes:**
- `db.py`: `TaskStoreUnavailableError`, `conninfo()` (reads `DATABASE_URL` on each call, `""` falls back to libpq `PG*`), `connect()` context manager with `connect_timeout=3`, `options="-c statement_timeout=5000 -c TimeZone=UTC"`, `application_name="taskboard28-api"`; maps `psycopg.OperationalError` / `InterfaceError` to `TaskStoreUnavailableError` and logs `task_store_unavailable` (class name only, never the DSN).
- `db.py`: `MIGRATIONS = [(1, <CREATE TABLE tasks ...>)]` exactly as in design "Data"; `ensure_schema()` creates `schema_migrations` if missing and applies pending versions in one transaction under `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, sets `_schema_ready`, logs `db_schema_applied`; `connect()` applies them first while `_schema_ready` is false.
- `db.py`: `check_ready() -> bool` with `connect_timeout=2`, `statement_timeout_ms=2000`, `SELECT 1`; never raises.
- SQL only as module constants with `%s` parameters (bandit).
- `docs/env-vars.md`: a "Database" section for `DATABASE_URL` and the `PG*` fallback, with the timeouts.

**Done when:** the existing suite passes against the test Postgres (`test_health`, `test_contract`, spec 001 tests on the still in-memory store), `db.ensure_schema()` on an empty database creates both tables, and `devbox run ci` is green.

## t2 — Back TaskStore with Postgres

**Files:** src/taskboard28_api/tasks/store.py, tests/test_task_store.py
**Covers:** AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6, AC-002.7
**Goal:** `TaskStore` keeps its 001 interface but every call reads and writes the `tasks` table, so tasks survive restarts and the limit holds across replicas.

**Implementation notes:**
- Remove the list and the `threading.Lock`; `TaskStore()` takes no arguments and holds no state; `MAX_TASKS` and `TaskLimitReachedError` stay, so `tasks/__init__.py` is unchanged.
- `add`: inside `db.connect()`, `SELECT pg_advisory_xact_lock(TASKS_LIMIT_LOCK_KEY)`, `SELECT count(*) FROM tasks`, raise `TaskLimitReachedError` at `>= MAX_TASKS`, else `INSERT ... (id, title, due_date, created_at) VALUES (%s, ...) RETURNING id, title, due_date, created_at` with `uuid4()` and `datetime.now(UTC)`.
- `list`: `SELECT id, title, due_date, created_at FROM tasks ORDER BY seq`; `clear`: `TRUNCATE tasks`.
- One `_row_to_task(row) -> Task` for both paths: `id` as `str`, `created_at.astimezone(UTC)`.
- `TaskStoreUnavailableError` from `db.connect()` propagates unchanged.
- `tests/test_task_store.py`: keep the schema edge-case tests; make the store tests run on the test database (fresh store sees what an earlier instance stored, order, `list` returns a new list, `clear`, limit with `seed_tasks(1000)`), and add one test that a refused `DATABASE_URL` raises `TaskStoreUnavailableError` and stores nothing.

**Done when:** `tests/test_task_store.py` passes; the acceptance tests for AC-002.2 to AC-002.6 pass (the 503 parts of AC-002.7 need t3); spec 001's AC-001.7 test is retired by the testers as replaced.

## t3 — Answer 503 on store outages, apply the schema at startup, make /ready check the database

**Files:** src/taskboard28_api/tasks/api.py, src/taskboard28_api/main.py
**Covers:** AC-002.1, AC-002.7, AC-002.8
**Goal:** the HTTP layer answers the contract's `503` and readiness while the database is down and recovers without a restart.

**Implementation notes:**
- `api.py`: in both handlers, catch `db.TaskStoreUnavailableError` and raise `HTTPException(503, "task store unavailable")`; keep the `409` mapping and the existing log events.
- `main.py`: add a FastAPI `lifespan` that calls `db.ensure_schema()`; on `TaskStoreUnavailableError` log `db_schema_deferred` and continue (never exit).
- `main.py`: `/ready` returns `200 {"status": "ready"}` when `db.check_ready()` is true, else `JSONResponse(503, {"detail": "task store unavailable"})`; `/health`, `/ping`, `/metrics` unchanged.

**Done when:** the acceptance tests for AC-002.1, AC-002.7 and AC-002.8 pass once t2 is merged too, `test_health` passes against the test database, and `devbox run ci` is green.

## t4 — Map 422 validation errors to the contract's title types

**Files:** src/taskboard28_api/tasks/schemas.py, src/taskboard28_api/tasks/api.py, src/taskboard28_api/main.py
**Covers:** none (the shared contract of the system plan, `contract/001-tasks-in-postgres-visible-and-creatable.json`)
**Goal:** `422` bodies carry `type` `title-required`, `title-min` and `title-max` for a missing, empty and over-long `title`, as `tests/test_contract.py` expects (today FastAPI answers `missing`, `string_too_short`, `string_too_long`).

**Implementation notes:**
- Map the pydantic error types of `title` to the contract types in `schemas`/`api` (a `RequestValidationError` handler or custom validator messages); keep the rest of the `422` body of spec 001.
- Validation still runs before the handler, so it also answers `422` during an outage.

**Done when:** `tests/test_contract.py` passes and `devbox run ci` is green.
