# Verification — 001 Create and list tasks in memory

**Result:** pass
**Commit:** 4dfc3b4 · **Base:** 203de80 · **Trace:** 8/8 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks_acceptance.py::test_ac_001_1_create_task_with_due_date`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/taskboard28_api/tasks/api.py:28-37`, `src/taskboard28_api/tasks/store.py:26-37`, `src/taskboard28_api/main.py:24` | asserts 201, non-empty string `id`, `title`, `due_date` `"2026-12-24"`, `created_at` parsed with UTC offset 0 |
| AC-001.2 | met | `tests/test_tasks_acceptance.py::test_ac_001_2_create_task_without_due_date` | `src/taskboard28_api/tasks/schemas.py:23,28-29` | both absent and explicit `null` asserted 201 with `due_date` null |
| AC-001.3 | met | `tests/test_tasks_acceptance.py::test_ac_001_3_invalid_title_is_422` (missing, `42`, `""`, whitespace, 201 chars, 201 chars after trim), `::test_ac_001_3_title_of_200_chars_after_trim_is_accepted` | `src/taskboard28_api/tasks/schemas.py:19-22` | asserts 422, `["body","title"]` in `detail[*].loc`, and `GET /tasks` == `[]` (no task created); 200-after-trim boundary accepted and returned trimmed |
| AC-001.4 | met | `tests/test_tasks_acceptance.py::test_ac_001_4_invalid_due_date_is_422` (all three spec examples) | `src/taskboard28_api/tasks/schemas.py:11,25-35` | asserts 422, `["body","due_date"]` in locs, list stays `[]` |
| AC-001.5 | met | `tests/test_tasks_acceptance.py::test_ac_001_5_list_in_creation_order`; smoke `tests/test_smoke_tasks.py::test_smoke_ac_001_5_list_in_creation_order` | `src/taskboard28_api/tasks/api.py:40-43`, `src/taskboard28_api/tasks/store.py:39-41` | asserts 200 and the list equals the three creation responses in order A, B, C |
| AC-001.6 | met | `tests/test_tasks_acceptance.py::test_ac_001_6_fresh_list_is_empty` | `src/taskboard28_api/tasks/store.py:22-23`, `src/taskboard28_api/tasks/api.py:40-43` | asserts 200 and `[]` |
| AC-001.7 | met | `tests/test_tasks_acceptance.py::test_ac_001_7_restart_empties_list` | `src/taskboard28_api/tasks/api.py:15-20` (process-local store), `src/taskboard28_api/tasks/store.py:22-24` | restart modelled as a fresh `TaskStore()`, as the design's contract states; no persistence anywhere in the diff |
| AC-001.8 | met | `tests/test_tasks_acceptance.py::test_ac_001_8_limit_of_1000_tasks` | `src/taskboard28_api/tasks/store.py:12,28-29`, `src/taskboard28_api/tasks/api.py:33-35` | 1000 creates via HTTP, 1001st asserts 409 with `{"detail": "task limit of 1000 reached"}`, list still exactly 1000 with last `t999`; check and append under one lock |

Unit tests in `tests/test_task_store.py` additionally exercise the store and schema edges (copy semantics, `"20261224"`, integer `due_date`, `None` title).

## Non-goals

No database or persistence, no single-task read/update/delete, no filtering/sorting/pagination, no auth, no shared storage. Template-owned files untouched apart from the planned `include_router` in `main.py`. ✔

## Deviations from the plan

- `tests/test_tasks_acceptance.py` and `tests/test_smoke_tasks.py` are in no task's `files`: they are the frozen acceptance tests from the red phase (commits 8eba801, 024997e); acceptable.
- `design.md` and `plan.md` added by the plan phase; acceptable.
- Both tasks `t1`, `t2` are `done: true`. Open human step: confirm `replicas: 1` in the gitops `system.yaml` (A9); outside this repo.

## Contract

No `contract/` copy (no shared plan rules). Implementation matches `design.md`: 201 + Task object, FastAPI 422 with field `loc`, 409 body `{"detail": "task limit of 1000 reached"}`, `GET /tasks` array in creation order, unknown fields ignored (`extra="ignore"`, `schemas.py:17`). ✔

## Smoke

`tests/test_smoke_tasks.py::test_smoke_ac_001_5_list_answers_with_array` is the read-only check the design asks for (200 + JSON array); it fails without the route (404 raises), so it is no smoke-only pass. AC-001.5 order is proven by the writing smoke test beside it. No SMOKE findings.

## Test review

Review commit 024997e: `findings: 0`. No unresolved findings.

## Mutation check (report only)

15 of 18 mutants of the changed code were caught by the acceptance tests (83 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard28_api/tasks/api.py:20 return value → None`
- `src/taskboard28_api/tasks/schemas.py:30 or → and`
- `src/taskboard28_api/tasks/schemas.py:21 True → False`
