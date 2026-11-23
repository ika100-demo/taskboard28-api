---
spec_id: 002-keep-tasks-in-postgres-so-they-survive
title: Keep tasks in Postgres so they survive restarts
status: approved
priority: P1
shape: service-python
parent: ika100-demo/taskboard28-gitops:001-tasks-in-postgres-visible-and-creatable
---

# 002 — Keep tasks in Postgres so they survive restarts

## Problem

The Task API keeps tasks in memory: every restart or redeploy of taskboard28-api loses all tasks, and with only one instance at most 1000 tasks fit. The website taskboard28-web shows nothing yet, so a person can only reach tasks by calling the API by hand. Keeping tasks in a Postgres database and giving people a page to see and create them turns taskboard28 into something people can actually use.

## System context

Slice of the system plan `001-tasks-in-postgres-visible-and-creatable` in `ika100-demo/taskboard28-gitops` for `taskboard28-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks created through `POST /tasks` or the website, when taskboard28-api is restarted or redeployed, then `GET /tasks` returns `200` with the same tasks (same `id`, `title`, `due_date` and `created_at`) in creation order, and the website lists them too.
- **AC-001.2** Given tasks "A" (due `2026-12-24`) and "B" (no due date) created in that order, through the API or the website, when a person opens the website's start page, then it shows a task list with "A" followed by "B", each showing its title, and its due date as `2026-12-24` or the text "No due date".
- **AC-001.3** Given no task exists, when a person opens the website's start page, then it shows the text "No tasks yet" instead of a list, together with the create form.
- **AC-001.4** Given the website's start page, when a person enters the title "Buy milk", picks the due date 2026-12-24 (or leaves it empty) and submits the form, then without leaving the page the new task appears last in the list with that title and due date (or "No due date"), the form is cleared, and `GET /tasks` on the API returns the task.
- **AC-001.5** Given the website's create form, when a person submits it with an empty or whitespace-only title, or a title longer than 200 characters, then the form shows "Title is required" or "Title must be at most 200 characters" next to the title field, keeps the entered values, and no task is created.
- **AC-001.6** Given 1000 tasks already exist, when a person submits a valid task on the website, then the form shows "The task limit of 1000 is reached", keeps the entered values, and the list still shows exactly 1000 tasks.
- **AC-001.8** Given the database is unreachable, when a client sends `GET /tasks` or `POST /tasks`, then the response is `503` with an error saying the task store is unavailable, no task is created, and once the database is reachable again all tasks stored before are returned.

### Contract

taskboard28-api, reached by the website at `TASKBOARD28_API_URL` (dev: `http://taskboard28-api`) and from outside
at its own dev URL (A9). JSON bodies, snake_case. No authentication (A10). Unchanged from taskboard28-api spec 001
except that tasks are stored in Postgres and `503` is new.

**Task object**

| field | type | notes |
|---|---|---|
| `id` | string | server-assigned UUID, opaque |
| `title` | string | trimmed, 1 to 200 characters |
| `due_date` | string or `null` | calendar date `YYYY-MM-DD` |
| `created_at` | string | ISO 8601 UTC timestamp, set by the server |

**`GET /tasks`**

- `200`: JSON array of all task objects in creation order, oldest first; `[]` when none exists.
- `503`: `{"detail": "task store unavailable"}` when the database is unreachable or slow.

**`POST /tasks`**

- Request: `{"title": "<string>", "due_date": "<YYYY-MM-DD>" | null}`; `due_date` may be omitted; unknown fields
  are ignored.
- `201`: the created task object.
- `422`: validation error (see Errors); no task created.
- `409`: `{"detail": "task limit of 1000 reached"}` when 1000 tasks are stored; no task created.
- `503`: `{"detail": "task store unavailable"}` when the database is unreachable or slow; no task created.

**Probes:** `GET /health` `200` while the process runs; `GET /ready` `200` only while the database answers,
else `503` (A8), so Kubernetes routes no traffic to the API during an outage.

### Rules

```yaml
rules:
  - id: title-required
    endpoint: POST /tasks
    field: title
    kind: required
    value: true
    provider: taskboard28-api
    consumers: [taskboard28-web]
  - id: title-min
    endpoint: POST /tasks
    field: title
    kind: min_length
    value: 1
    provider: taskboard28-api
    consumers: [taskboard28-web]
  - id: title-max
    endpoint: POST /tasks
    field: title
    kind: max_length
    value: 200
    provider: taskboard28-api
    consumers: [taskboard28-web]
```

Prose rules no tool checks:

- Lengths count the title after trimming leading and trailing whitespace; a whitespace-only title counts as empty.
  The API stores and returns the trimmed title; the website sends the trimmed title.
- `due_date` is `YYYY-MM-DD` or `null`; past dates are accepted. The website sends the value of the browser's date
  input as is, or `null` when it is empty; any other form answers `422` with `loc` ending in `due_date`.
- The website's own messages for a title it rejects before sending are "Title is required" (missing, empty,
  whitespace-only) and "Title must be at most 200 characters".

### Errors

```yaml
errors:
  status: 422
  body:
    list: detail
    field: loc
    rule: type
    message: msg
  unlisted:
    message: "The task could not be saved. Try again."
```

The `422` body is FastAPI's standard one: `{"detail": [{"loc": ["body", "title"], "type": "...", "msg": "..."}]}`.
The website takes the field from the last element of `loc` (a plain string `loc` is the field itself) and shows
that item's `msg` next to that field, keeping the entered values.

Other listed answers on `POST /tasks`: `409` shows "The task limit of 1000 is reached"; `503` shows the unlisted
message. Any answer the contract does not list (another status, a body that is not JSON, a network error or a
timeout) shows "The task could not be saved. Try again." on the form and keeps the entered values. On `GET /tasks`,
anything but `200` with a JSON array shows "Tasks could not be loaded. Try again later." instead of the list.

### Timeouts

- **taskboard28-web -> taskboard28-api** `GET /tasks` and `POST /tasks`: 10 seconds each, no retry (a retried
  `POST` could create a task twice). A timeout or a refused connection is treated as an unlisted answer (texts
  above). The page itself still renders, with the create form.
- **taskboard28-api -> Postgres**: connect timeout 3 seconds, statement timeout 5 seconds; either answers the
  request with `503 {"detail": "task store unavailable"}` and writes nothing. The API does not crash or exit while
  the database is down; it reconnects on the next request once the database is back.
- **`/ready`**: checks the database with a 2-second timeout, so a readiness probe never hangs; `/health` never
  touches the database.

### Contract rules

Copy: `contract/001-tasks-in-postgres-visible-and-creatable.json`, from plan `001-tasks-in-postgres-visible-and-creatable` at `ika100-demo/taskboard28-gitops@6b9f792`. The repo's contract check reads it.

| Rule | Endpoint | Field | Kind | Value | Status | Role |
|---|---|---|---|---|---|---|
| title-max | POST /tasks | title | max_length | 200 | 422 | provider |
| title-min | POST /tasks | title | min_length | 1 | 422 | provider |
| title-required | POST /tasks | title | required | True | 422 | provider |

Errors: status 422; body `detail[]` of objects with `loc`, `type`, `msg`; responses the contract does not list: show "The task could not be saved. Try again.".

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`

### Notes for this repo

Config only from env: DATABASE_URL (and PG*) injected by the gitops `uses: postgres`. The schema is created or
migrated by the service itself at start. Endpoints, fields, validation and the 409 limit are unchanged from the
repo's spec 001 (system A2); only storage changes. Tests run against a real Postgres (e.g. testcontainers).

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given an empty Postgres database at DATABASE_URL, when the service starts, then `/ready` answers `200` and `POST /tasks` with `{"title": "Buy milk"}` answers `201`, without any manual schema step (system AC-001.1)
- **AC-002.2** Given tasks created through `POST /tasks`, when the service is restarted or redeployed against the same database, then `GET /tasks` returns `200` with the same tasks (same `id`, `title`, `due_date` and `created_at`) in creation order (system AC-001.1) (replaces AC-001.7)
- **AC-002.3** Given tasks "A" with `due_date` `2026-12-24` and then "B" without `due_date` created through `POST /tasks`, when a client sends `GET /tasks`, then the response is `200` with "A" (`due_date` `"2026-12-24"`) followed by "B" (`due_date` `null`), the last one being the task returned by the latest `201` (system AC-001.2, AC-001.4)
- **AC-002.4** Given no task is stored in the database, when a client sends `GET /tasks`, then the response is `200` with an empty JSON array `[]` (system AC-001.3) (replaces AC-001.6)
- **AC-002.5** Given a `POST /tasks` whose `title` is missing, not a string, empty or whitespace-only, or longer than 200 characters after trimming, when it is sent, then the response is `422` with a `detail` item whose `loc` ends in `title`, and no task is stored (system AC-001.5)
- **AC-002.6** Given 1000 tasks are stored in the database (also after a restart), when a client sends a valid `POST /tasks`, then the response is `409` with `{"detail": "task limit of 1000 reached"}` and `GET /tasks` still returns exactly 1000 tasks (system AC-001.6)
- **AC-002.7** Given the database is unreachable or does not answer within 5 seconds, when a client sends `GET /tasks` or `POST /tasks`, then the response is `503` with `{"detail": "task store unavailable"}`, no task is stored, `/ready` answers `503` and `/health` still answers `200` (system AC-001.8)
- **AC-002.8** Given the database became reachable again after an outage, when a client sends `GET /tasks` without the service being restarted, then the response is `200` with all tasks stored before the outage and `/ready` answers `200` (system AC-001.8)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-23 created from the system plan, with its criteria (spec 147)
- 2026-11-23 approved
