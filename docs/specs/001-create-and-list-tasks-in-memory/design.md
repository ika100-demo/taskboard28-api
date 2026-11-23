# Design — 001 Create and list tasks in memory

## Decisions

- Tasks live in a new package `taskboard28_api/tasks/` (schemas, store, router), included into the existing `app` in `main.py`. One package per resource keeps `main.py` to wiring and gives later specs (a database, auth) one place to change.
- The store is a process-local `TaskStore` (list + `threading.Lock`), one instance per process, reached by the router through the FastAPI dependency `get_task_store`. The handlers are sync and run in the threadpool, so the limit check and the append happen under the lock; without it two concurrent creates at 999 could both pass (AC-001.8). A database later replaces the store behind the same dependency.
- A "restart" in tests is a fresh `TaskStore()` (AC-001.7): the only state is the store instance, nothing is written to disk or env.
- Validation uses Pydantic v2 with strict types, not lax coercion: `title` is `StrictStr` (a number is a `422`, not `"42"`), and `due_date` is a strict string matched against `^\d{4}-\d{2}-\d{2}$` and then `date.fromisoformat`. Pydantic's own `date` type would accept `"2026-12-24T00:00:00Z"`, unix integers and (via `fromisoformat` on 3.12) `"20261224"`, which AC-001.4 rejects.
- The task limit is a module constant `MAX_TASKS = 1000`, not an env variable: the spec fixes the number and the bound protects memory (A7); making it configurable is not asked for.
- Error bodies are FastAPI's standard ones (A4): `422` from request validation, `409` via `HTTPException`. No custom error format.
- No ADR: the in-memory store is explicitly temporary and the package layout is feature-local.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard28_api/tasks/__init__.py` | re-exports `router`, `TaskStore`, `get_task_store` | new |
| `src/taskboard28_api/tasks/schemas.py` | `TaskCreate` (request), `Task` (response) | new |
| `src/taskboard28_api/tasks/store.py` | `TaskStore`, `TaskLimitReachedError`, `MAX_TASKS` | new |
| `src/taskboard28_api/tasks/api.py` | `router` with `POST /tasks`, `GET /tasks`; `get_task_store` dependency | new |
| `src/taskboard28_api/main.py` | `app.include_router(tasks.router)` | changed |

```python
# schemas.py
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]

class TaskCreate(BaseModel):          # extra fields ignored (A8): model_config extra="ignore"
    title: Title
    due_date: date | None = None      # field_validator(mode="before"): None passes; else must be str
                                      # matching ^\d{4}-\d{2}-\d{2}$ and date.fromisoformat() -> date;
                                      # anything else raises ValueError -> 422 with loc ["body","due_date"]

class Task(BaseModel):
    id: str                           # str(uuid4())
    title: str                        # trimmed
    due_date: date | None             # serialised "YYYY-MM-DD" or null
    created_at: datetime              # datetime.now(UTC), serialised ISO 8601 with "Z" or "+00:00"

# store.py
MAX_TASKS: Final = 1000
class TaskLimitReachedError(Exception): ...
class TaskStore:
    def add(self, data: TaskCreate) -> Task          # under lock: if len >= MAX_TASKS raise TaskLimitReachedError
    def list(self) -> list[Task]                     # copy, creation order
    def clear(self) -> None

# api.py
_store = TaskStore()
def get_task_store() -> TaskStore: return _store
router = APIRouter(tags=["tasks"])
```

## Contract

Base path is the service root (A1). JSON bodies, snake_case. No authentication (A10).

**Task object** (every response that returns a task):

| Field | Type | Notes |
|---|---|---|
| `id` | string | non-empty, opaque (a UUID4 string); clients must not parse it (A5) |
| `title` | string | 1-200 characters, leading/trailing whitespace trimmed (A3) |
| `due_date` | string \| null | `YYYY-MM-DD` calendar date, or `null` (A2) |
| `created_at` | string | ISO 8601 UTC timestamp, e.g. `2026-11-23T10:15:30.123456Z` (offset `Z` or `+00:00`) |

**`POST /tasks`** — request body:

```json
{"title": "Buy milk", "due_date": "2026-12-24"}
```

- `title` required, string; trimmed, then 1 to 200 characters.
- `due_date` optional; absent or `null` means `null`; otherwise a string exactly `YYYY-MM-DD` that is a real calendar date (past dates accepted).
- Unknown fields are ignored (A8).

Responses:

- `201` + Task object (AC-001.1, AC-001.2). `Content-Type: application/json`.
- `422` on invalid input (AC-001.3, AC-001.4), FastAPI's standard body; the offending field is the last element of `loc`:
  ```json
  {"detail": [{"type": "string_too_short", "loc": ["body", "title"], "msg": "...", "input": "  "}]}
  ```
  Tests assert `422` and that some `detail[*].loc` equals `["body", "title"]` or `["body", "due_date"]`; `type` and `msg` are not part of the contract. A body that is not a JSON object also answers `422` (`loc` `["body"]`). No task is stored.
- `409` when 1000 tasks are already held (AC-001.8):
  ```json
  {"detail": "task limit of 1000 reached"}
  ```
  Validation runs first: an invalid body at the limit answers `422`.

**`GET /tasks`** — no parameters.

- `200` + JSON array of Task objects in creation order, oldest first (AC-001.5, A6); `[]` when there are none (AC-001.6, AC-001.7). No pagination (non-goal).

### For the acceptance tests (in-process)

- The store is module state, so tests isolate it with a fresh store per test, in their own test file (not `conftest.py`):
  ```python
  from taskboard28_api.main import app
  from taskboard28_api.tasks import TaskStore, get_task_store
  store = TaskStore(); app.dependency_overrides[get_task_store] = lambda: store
  # teardown: app.dependency_overrides.pop(get_task_store, None)
  ```
- A restart (AC-001.7) is swapping in a new `TaskStore()` between the creates and the `GET`.
- AC-001.8 may fill the store through 1000 `POST /tasks` calls or through `store.add(TaskCreate(title=...))`; both are contract.

### Smoke

AC-001.1 and AC-001.5 are smoke criteria. Creating tasks writes, so those smoke tests carry `@pytest.mark.writes` and use titles `smoke-<uuid>`; AC-001.5 checks that its own three tasks appear in that relative order (other tasks may exist on a shared instance). Add one read-only smoke check, `GET /tasks` answers `200` with a JSON array, so staging and prod have a passing check.

## Data

In memory only: a Python list of `Task` in the single `TaskStore`, at most 1000 entries (about a few hundred KB). Lost on restart (AC-001.7). Single replica assumed (A9); the gitops entry must keep `replicas: 1`.
