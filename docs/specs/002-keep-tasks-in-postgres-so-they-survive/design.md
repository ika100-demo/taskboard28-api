# Design — 002 Keep tasks in Postgres so they survive restarts

## Decisions

- **Driver: psycopg 3 (`psycopg[binary]`), sync, one connection per database call, no pool.** The handlers stay sync (threadpool) like in 001. A fresh connection per call makes outage and recovery trivial: nothing stale survives an outage, so the first request after the database is back succeeds without a restart (AC-002.8), and libpq's `connect_timeout` bounds a database that accepts TCP but does not answer (AC-002.7). At most 1000 small rows and low traffic make the few ms per connect irrelevant; a pool is a later optimisation behind the same `db.connect()`.
- **Timeouts (spec "Timeouts"):** every call connects with `connect_timeout=3` and `options="-c statement_timeout=5000 -c TimeZone=UTC"`; `/ready` uses `connect_timeout=2` and `statement_timeout=2000`. Any `psycopg.OperationalError` (connection refused, connect timeout, `QueryCanceled` from the statement timeout, connection lost) or `psycopg.InterfaceError` becomes `TaskStoreUnavailableError`, answered `503 {"detail": "task store unavailable"}` (AC-002.7). The process never exits on a database error.
- **Config:** `DATABASE_URL`, read from `os.environ` on every connect (not at import), so tests can point it elsewhere per test. When it is unset or empty the conninfo is `""` and libpq falls back to `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` (both are injected by the gitops `uses: postgres`). No new settings class.
- **Schema by the service itself (Notes for this repo, AC-002.1):** a tiny ordered migration list in `db.py` (`MIGRATIONS: list[tuple[int, str]]`) plus a `schema_migrations(version)` table, applied by `ensure_schema()` inside one transaction under `pg_advisory_xact_lock(SCHEMA_LOCK_KEY)`, so two replicas starting at once do not race. It runs at startup (FastAPI lifespan); if the database is down then, startup logs `db_schema_deferred` and continues, and the first successful `db.connect()` applies it (module flag `_schema_ready`). No Alembic: one table does not justify it; a later spec can swap the runner, keeping the version numbers.
- **One `TaskStore`, now Postgres-backed, same interface as 001** (`TaskStore()`, `add`, `list`, `clear`, `MAX_TASKS`, `TaskLimitReachedError`). The in-memory implementation is removed. The store holds no state, so `TaskStore()` anywhere talks to the same database, and the 001 tests' `dependency_overrides[get_task_store] = lambda: TaskStore()` keep working.
- **Creation order** is a server-side identity column `seq`, `ORDER BY seq`; `created_at` alone could tie (AC-002.2, AC-002.3).
- **Task limit across replicas (AC-002.6):** `add` runs `SELECT pg_advisory_xact_lock(TASKS_LIMIT_LOCK_KEY)`, then `count(*)`, then `INSERT ... RETURNING` in one transaction, so two concurrent creates at 999 cannot both pass, also with several replicas. The limit stays the module constant `MAX_TASKS = 1000`.
- **Values round-trip exactly (AC-002.2):** `id` (`uuid4`) and `created_at` (`datetime.now(UTC)`) are generated in Python and inserted; the returned `Task` of both `POST` and `GET` is built from the database row by one function (`_row_to_task`), with `created_at.astimezone(UTC)`, so the `201` body equals the later `GET` item field for field.
- **Validation is unchanged** (`schemas.py` untouched): it runs before the handler, so an invalid body during an outage still answers `422`. A `CHECK (char_length(title) BETWEEN 1 AND 200)` is a second line of defence only.
- **`/ready`** answers `200 {"status": "ready"}` when `SELECT 1` succeeds within 2 s (and the schema is applied), else `503 {"detail": "task store unavailable"}`. `/health` is unchanged and never touches the database.
- **Tests run against a real Postgres (Notes for this repo):** `testcontainers[postgres]` with `postgres:16-alpine`, started once per session and only when a non-smoke test runs; `TEST_DATABASE_URL`, when set, is used instead (no Docker needed). The fixtures live in `tests/conftest.py`, owned by plan task t1.
- **ADR:** Postgres with psycopg 3, connection-per-call and self-applied migrations is a decision that outlives this feature. To be created by the orchestrator with `cplat adr add postgres-task-store --decision "Tasks are stored in Postgres via psycopg 3, one connection per call, schema applied by the service at start from an ordered migration list"` (this run had no shell to call `cplat`).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard28_api/db.py` | conninfo from env, `connect()`, `ensure_schema()`, `check_ready()`, `TaskStoreUnavailableError`, migrations | new (t1) |
| `src/taskboard28_api/tasks/store.py` | `TaskStore` on Postgres; `MAX_TASKS`, `TaskLimitReachedError` kept | changed (t2) |
| `src/taskboard28_api/tasks/api.py` | maps `TaskStoreUnavailableError` to `503` | changed (t3) |
| `src/taskboard28_api/main.py` | lifespan runs `ensure_schema()`; `/ready` uses `check_ready()` | changed (t3) |
| `tests/conftest.py` | Postgres session fixture, autouse clean-up, `seed_tasks`, `empty_database` | changed (t1) |
| `pyproject.toml`, `uv.lock` | `psycopg[binary]>=3.2`; dev `testcontainers[postgres]>=4.8` | changed (t1) |
| `docs/env-vars.md` | `DATABASE_URL`, `PG*` | changed (t1) |

```python
# db.py
class TaskStoreUnavailableError(Exception): ...       # database unreachable, too slow or connection lost

SCHEMA_LOCK_KEY: Final = 2028_0001                    # pg_advisory_xact_lock keys (bigint constants)
TASKS_LIMIT_LOCK_KEY: Final = 2028_0002
MIGRATIONS: Final[list[tuple[int, str]]] = [(1, CREATE_TASKS_SQL)]

def conninfo() -> str                                 # os.environ.get("DATABASE_URL", "") ; "" -> libpq PG* env
@contextmanager
def connect(*, connect_timeout: int = 3, statement_timeout_ms: int = 5000) -> Iterator[psycopg.Connection]
    # psycopg.connect(conninfo(), connect_timeout=..., options=f"-c statement_timeout={ms} -c TimeZone=UTC",
    #                 application_name="taskboard28-api")
    # if not _schema_ready: _apply_migrations(conn)
    # yields conn inside `with conn:` (commit on success, rollback on error), closes it afterwards
    # psycopg.OperationalError | psycopg.InterfaceError -> raise TaskStoreUnavailableError from exc
def ensure_schema() -> None                           # always applies pending migrations (lifespan, test fixtures); sets _schema_ready
def check_ready() -> bool                             # connect(connect_timeout=2, statement_timeout_ms=2000); SELECT 1; False on TaskStoreUnavailableError

# tasks/store.py
MAX_TASKS: Final = 1000
class TaskLimitReachedError(Exception): ...
class TaskStore:                                      # stateless; every method opens db.connect()
    def add(self, data: TaskCreate) -> Task           # advisory lock, count, INSERT ... RETURNING; raises TaskLimitReachedError / TaskStoreUnavailableError
    def list(self) -> list[Task]                      # SELECT ... ORDER BY seq; new list each call
    def clear(self) -> None                           # TRUNCATE tasks
```

SQL is module constants with `%s` parameters only, never f-strings with values (bandit B608).

## Contract

Unchanged from spec 001's design (Task object, `POST /tasks`, `GET /tasks`, `422` body, `409` body), except:

- Tasks are stored in Postgres: they survive restarts and redeploys and are shared by all replicas (AC-002.2). `GET /tasks` is all stored tasks in creation order, oldest first.
- **`503`** on `GET /tasks` and `POST /tasks` when the database is unreachable, does not accept a connection within 3 s, or a statement does not finish within 5 s (AC-002.7):
  ```json
  {"detail": "task store unavailable"}
  ```
  No task is stored. A body that fails validation answers `422` first, also during an outage. A `POST` at the limit answers `409` only when the database is reachable.
- **`GET /ready`**: `200 {"status": "ready"}` while the database answers `SELECT 1` within 2 s; otherwise `503 {"detail": "task store unavailable"}` (AC-002.7, AC-002.8). Never hangs longer than about 2 s.
- **`GET /health`**: `200 {"status": "ok"}` always, independent of the database (AC-002.7).
- Recovery needs no restart: the first request after the database is back answers normally (AC-002.8).
- Logs: `task_store_unavailable` (warning, field `error` = exception class name; never the DSN, password or title), `db_schema_applied` (`version`), `db_schema_deferred`.

### For the acceptance tests (in-process, real Postgres)

Fixtures in `tests/conftest.py` (t1); testers use them and do not edit `conftest.py`:

| Fixture | Scope | What it gives |
|---|---|---|
| `postgres_dsn` | session | DSN of the test database (`TEST_DATABASE_URL` or a `postgres:16-alpine` testcontainer); sets `DATABASE_URL` to it for the session |
| autouse `_tasks_db` | function | for every test not marked `smoke`: requests `postgres_dsn`, runs `db.ensure_schema()` and `TRUNCATE tasks` before the test, so each test starts with an empty, migrated database |
| `seed_tasks` | function | callable `seed_tasks(n: int) -> None`: inserts `n` valid tasks (`title` `seed-<i>`, `due_date` null) in one SQL statement, in order, for the 1000-task criterion without 1000 HTTP calls |
| `empty_database` | function | drops `tasks` and `schema_migrations`, so the database is as new (AC-002.1) |

- **Service start / restart** (AC-002.1, AC-002.2, AC-002.6): `with TestClient(app) as client:` runs the lifespan (schema applied). A restart is leaving that block and entering a new one; the database stays. Data must not be kept in the process: a `TaskStore()` created after the restart sees the same tasks.
- **Database unreachable** (AC-002.7): `monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:1/x")` (connection refused, fast). Monkeypatch restores the real DSN at teardown.
- **Database does not answer within 5 s** (AC-002.7): in a separate connection to `postgres_dsn`, `BEGIN; LOCK TABLE tasks IN ACCESS EXCLUSIVE MODE;` and hold it while the client sends `GET /tasks` or `POST /tasks`; the statement timeout answers `503` after about 5 s. Release the lock (rollback) at the end, then assert nothing was stored.
- **Back after the outage** (AC-002.8): after the unreachable phase, `monkeypatch.setenv("DATABASE_URL", postgres_dsn)` (or `monkeypatch.undo()`) and send `GET /tasks` on the same client and app, without a new lifespan.
- Spec 001's acceptance test for the replaced AC-001.7 ("restart empties the list") contradicts AC-002.2 and is retired by the testers; the tests for AC-001.6 (now AC-002.4) keep passing thanks to the autouse clean-up.

### Smoke

The existing smoke tests keep working. AC-002.3 is a writing smoke check (`smoke-<uuid>` titles, own tasks in relative order). Read-only checks for staging and prod: `GET /ready` answers `200` (the database is wired) and `GET /tasks` answers `200` with an array (exists).

## Data

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    integer PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

-- migration 1
CREATE TABLE tasks (
    seq        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,   -- creation order
    id         uuid NOT NULL UNIQUE,
    title      text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date   date NULL,
    created_at timestamptz NOT NULL
);
```

At most 1000 rows (`MAX_TASKS`). Responses expose `id` as its canonical string, never `seq`. The database itself (instance, credentials, backups) is provided by the system (`uses: postgres`); this repo needs no gitops change.
