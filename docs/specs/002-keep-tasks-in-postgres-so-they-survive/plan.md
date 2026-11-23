---
spec_id: 002-keep-tasks-in-postgres-so-they-survive
shape: service-python
spec_hash: 35a8e3a6e42f
summary: Tasks stored in Postgres via psycopg 3 (connection per call, self-applied schema), 503 and a database-aware /ready during outages
tasks:
  - id: t1
    title: Add the db module (conninfo, timeouts, migrations, readiness) and the Postgres test fixtures
    files: [src/taskboard28_api/db.py, pyproject.toml, uv.lock, tests/conftest.py, docs/env-vars.md]
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
---

# Plan — 002 Keep tasks in Postgres so they survive restarts

See [design.md](design.md) for the decisions, signatures, schema, contract and the test fixtures. No gitops task: the system plan wires `uses: postgres` (`DATABASE_URL`, `PG*`) for this component.

## t1 — Add the db module (conninfo, timeouts, migrations, readiness) and the Postgres test fixtures

**Files:** src/taskboard28_api/db.py, pyproject.toml, uv.lock, tests/conftest.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.7, AC-002.8
**Goal:** one module owns every database connection with the spec's timeouts and error mapping and applies the schema itself; the test suite gets a real Postgres.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` to `dependencies` and `testcontainers[postgres]>=4.8` to the `dev` extra; refresh `uv.lock` through `devbox shell` (its init hook runs `uv sync --all-extras`), never `uv add`.
- `db.py`: `TaskStoreUnavailableError`, `conninfo()` (reads `DATABASE_URL` on each call, `""` falls back to libpq `PG*`), `connect()` context manager with `connect_timeout=3`, `options="-c statement_timeout=5000 -c TimeZone=UTC"`, `application_name="taskboard28-api"`; maps `psycopg.OperationalError` / `InterfaceError` to `TaskStoreUnavailableError` and logs `task_store_unavailable` (class name only, never the DSN).
- `db.py`: `MIGRATIONS = [(1, <CREATE TABLE tasks ...>)]` exactly as in design "Data"; `ensure_schema()` creates `schema_migrations` if missing and applies pending versions in one transaction under `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, sets `_schema_ready`, logs `db_schema_applied`; `connect()` applies them first while `_schema_ready` is false.
- `db.py`: `check_ready() -> bool` with `connect_timeout=2`, `statement_timeout_ms=2000`, `SELECT 1`; never raises.
- SQL only as module constants with `%s` parameters (bandit).
- `tests/conftest.py`: keep `client`; add `postgres_dsn` (session; `TEST_DATABASE_URL` or a `postgres:16-alpine` `PostgresContainer`, started lazily; sets `os.environ["DATABASE_URL"]` for the session), autouse `_tasks_db` (skips tests marked `smoke`; else `db.ensure_schema()` + `TRUNCATE tasks`), `seed_tasks(n)` (one `INSERT ... SELECT ... FROM generate_series`, `uuid4`-like ids via `gen_random_uuid()`, `created_at` increasing, titles `seed-<i>`), `empty_database` (drops `tasks` and `schema_migrations`), all as in design.
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
