# Verification — 002 Keep tasks in Postgres so they survive restarts

**Result:** pass
**Commit:** 77aeec2 · **Base:** 0cbcf56 · **Trace:** 8/8 criteria named by tests (`tests/test_tasks_postgres_acceptance.py`)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_1_empty_database_starts_and_accepts_tasks` | `src/taskboard28_api/main.py:33-39`, `src/taskboard28_api/db.py:53-66,96-99`, `src/taskboard28_api/main.py:77-82` | `empty_database` drops both tables; the lifespan's `ensure_schema()` creates them; `/ready` 200 and `POST` 201 asserted, row read back through a fresh `TaskStore()` |
| AC-002.2 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_2_tasks_survive_restart` | `src/taskboard28_api/tasks/store.py:28-34,40-59`, `src/taskboard28_api/db.py:25-33` | full objects (`id`, `title`, `due_date`, `created_at`) compared after a second lifespan and via a fresh stateless `TaskStore()`, so an in-process store cannot pass; order by `seq` |
| AC-002.3 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_3_due_dates_and_order` | `src/taskboard28_api/tasks/store.py:21,55-58` | order A, B; `"2026-12-24"` and `null`; `body[-1] == b.json()` |
| AC-002.4 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_4_empty_database_lists_empty_array` | `src/taskboard28_api/tasks/store.py:55-58`, `src/taskboard28_api/tasks/api.py:45-51` | autouse `_tasks_db` truncates; `[]` asserted |
| AC-002.5 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_5_invalid_title_is_422_and_not_stored` (6 cases) | `src/taskboard28_api/tasks/schemas.py` (unchanged), `src/taskboard28_api/main.py:50-58` | missing, `42`, `""`, `"   "`, 201 chars, 201 chars padded; `loc[-1] == "title"`, list stays `[]` |
| AC-002.6 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_6_limit_of_1000_also_after_restart` | `src/taskboard28_api/tasks/store.py:40-47`, `src/taskboard28_api/tasks/api.py:38-40` | 1000 rows seeded by SQL, restart, exact `409` body, `len == 1000` |
| AC-002.7 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_7_unreachable_database_is_503` (l. 114), `::test_ac_002_7_database_not_answering_is_503` (l. 131), `::test_ac_002_7_silent_database_is_503_within_5_seconds` (l. 151) | `src/taskboard28_api/db.py:69-93,102-109`, `src/taskboard28_api/tasks/api.py:36-37,48-51`, `src/taskboard28_api/main.py:71-82` | Cycle-1 TEST LOOSER resolved. The new test points `DATABASE_URL` at a TCP listener that accepts and never replies: `GET` and `POST /tasks` each return `503` with the exact body within 5.5 s, `/ready` `503` within 5.5 s, `/health` `200`, and with the real DSN restored the list is `[]` (nothing stored). Bounded in code by `connect_timeout=3` (`db.py:71`) and `connect_timeout=2` for `/ready` (`db.py:105`); `statement_timeout=5000` (`db.py:71,78`) covers the lock case of l. 131 |
| AC-002.8 | met | `tests/test_tasks_postgres_acceptance.py::test_ac_002_8_recovers_after_outage_without_restart` | `src/taskboard28_api/db.py:69-93` (connection per call), `src/taskboard28_api/main.py:77-82` | same client and lifespan; tasks from before the outage returned, `/ready` 503 then 200 |

## Non-goals

The spec lists no non-goals. No code outside the spec's scope was added (no website, no gitops change, no pool). This is not a web shape, so the template layout check does not apply. ✔

## Deviations from the plan

- `tests/conftest.py`, `pyproject.toml`, `uv.lock` are in no task's `files`. The plan's t1 assigns them to the red-tests step. Acceptable.
- `tests/test_tasks_acceptance.py`: the AC-001.7 test was removed. AC-001.7 is struck through as superseded by AC-002.2 in `docs/specs/001-create-and-list-tasks-in-memory/spec.md`, as the t2 done-note and the design ask. Acceptable.
- `docs/specs/001-.../spec.md`, `docs/backlog.md`, `docs/adr/001-postgres-task-store.md`, `docs/adr/README.md`, `contract/001-...json`, `.secrets.baseline.json`: spec, ADR and contract bookkeeping outside the task files. Acceptable. The ADR's Context and Consequences sections are still empty placeholders. The backlog row shows 002 as `approved` while the spec says `building`; it is generated and will be refreshed.
- t4 lists `src/taskboard28_api/tasks/schemas.py` and `tasks/api.py` but only changed `main.py` (a `RequestValidationError` handler). Acceptable. The plan allowed either.
- `tests/test_tasks_postgres_acceptance.py` changed again in 77aeec2 (the AC-002.7 tightening). It is in t1's files. Acceptable.
- All tasks t1 to t4 are `done: true`.
- Design "Smoke" (`design.md:92-94`) promises a writing smoke check for AC-002.3 and read-only smoke checks (`GET /ready` 200, `GET /tasks` 200 array) for staging and prod. None were added: `tests/test_smoke_tasks.py` still covers only AC-001.1 and AC-001.5, and nothing in the smoke tests checks `/ready`. No criterion is marked `(smoke)`, so no criterion requires them. This does not fail any criterion, but the build does not match the design: add them, or remove that paragraph from the design.

## Contract

Matches `design.md` and the spec's Contract: `503 {"detail": "task store unavailable"}` on `GET`/`POST /tasks` (`tasks/api.py:36-37,48-51`); `/ready` gives `200 {"status": "ready"}` or `503` with the same body (`main.py:77-82`); `/health` does not touch the database (`main.py:71-74`); the `422` `type` is mapped to `title-required` / `title-min` / `title-max` for the shared contract rules (`main.py:43-58`); timeouts are 3 s / 5 s, and 2 s / 2 s for `/ready` (`db.py:71,78,105`). ✔

## Tightened acceptance tests

| File | Reason | Asserts the criterion as written |
|---|---|---|
| `tests/test_tasks_postgres_acceptance.py` | AC-002.7 (commit 77aeec2): adds `test_ac_002_7_silent_database_is_503_within_5_seconds`, a TCP socket that accepts and never replies; `GET /tasks`, `POST /tasks` and `GET /ready` each return `503` within 5.5 s, `/health` stays `200`, nothing is stored | yes: covers the 5 s bound and `/ready` 503 for a database that does not answer, the two gaps found in cycle 1. The 0.5 s margin is for test overhead; the code's own bound is 3 s (`db.py:71`) |

## Mutation check (report only)

1 of 20 mutants tested in 90 s (time budget of 90 s, `--budget`); the score covers the tested ones.

0 of 1 mutants of the changed code were caught by the acceptance tests (0 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard28_api/db.py:15 20280001 → 20280002`
