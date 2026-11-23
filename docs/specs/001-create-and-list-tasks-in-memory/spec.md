---
spec_id: 001-create-and-list-tasks-in-memory
title: Create and list tasks in memory
status: done
priority: P1
shape: service-python
---

# 001 — Create and list tasks in memory

## Problem

The Task API has no tasks yet: it only answers health and readiness checks, so a client of taskboard28 cannot record anything to do. This first feature lets a client create tasks with a title and an optional due date and list them back, kept in the service's memory, so that the API has its basic shape before any database is introduced.

## Stories

As a taskboard28 client, I want to create a task with a title and, if I have one, a due date, so that I can record what needs doing.

As a taskboard28 client, I want to list all tasks, so that I can see what has been recorded.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with `{"title": "Buy milk", "due_date": "2026-12-24"}`, then the response is `201` with a JSON object holding a server-assigned `id` (a non-empty string), `title` `"Buy milk"`, `due_date` `"2026-12-24"` and `created_at` (an ISO 8601 UTC timestamp). (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with `{"title": "Call Anna"}` and no `due_date` (or `"due_date": null`), then the response is `201` and the task's `due_date` is `null`.
- **AC-001.3** Given a running service, when a client sends `POST /tasks` with a missing `title`, a `title` that is not a string, a `title` that is empty or only whitespace after trimming, or a `title` longer than 200 characters after trimming, then the response is `422` with an error naming the `title` field, and no task is created.
- **AC-001.4** Given a running service, when a client sends `POST /tasks` with a `due_date` that is not a calendar date in `YYYY-MM-DD` form (such as `"24.12.2026"`, `"2026-02-30"` or `"2026-12-24T10:00:00Z"`), then the response is `422` with an error naming the `due_date` field, and no task is created.
- **AC-001.5** Given tasks "A", "B" and "C" created in that order, when a client sends `GET /tasks`, then the response is `200` with a JSON array of the three tasks in creation order, each with `id`, `title`, `due_date` and `created_at` as returned on creation. (smoke)
- ~~**AC-001.6**~~ superseded by AC-002.4 on 2026-11-23: Given no task has been created since the service started, when a client sends `GET /tasks`, then the response is `200` with an empty JSON array `[]`.
- ~~**AC-001.7**~~ superseded by AC-002.2 on 2026-11-23: Given tasks created before the service restarts, when a client sends `GET /tasks` after the restart, then the response is `200` with an empty JSON array, because tasks are kept in memory only.
- **AC-001.8** Given 1000 tasks already exist, when a client sends `POST /tasks` with a valid body, then the response is `409` with an error saying the task limit of 1000 is reached, and `GET /tasks` still returns exactly 1000 tasks.

## Non-goals

- Persisting tasks in a database or surviving a restart.
- Reading a single task, updating, completing or deleting tasks.
- Filtering, sorting options, search or pagination of the list.
- Users, ownership, authentication or any access control: a follow-up spec.
- Sharing tasks between several running instances of the service.

## Assumptions

- **A1** The endpoints are `POST /tasks` and `GET /tasks` with JSON bodies and snake_case field names (other option: `/api/v1/tasks`; affects AC-001.1 to AC-001.8).
- **A2** `due_date` is a calendar date without time or time zone, `YYYY-MM-DD`; past dates are accepted (other option: a full timestamp, or rejecting past dates; affects AC-001.1, AC-001.4).
- **A3** A title is trimmed of leading and trailing whitespace and must be 1 to 200 characters after trimming; the stored and returned title is the trimmed one (other option: 500 characters, no trimming; affects AC-001.3).
- **A4** Validation errors answer `422` with the framework's standard error body naming the field (other option: `400` with a custom error body; affects AC-001.3, AC-001.4).
- **A5** The id is an opaque server-generated string (a UUID), not a sequential number (other option: integer ids from 1; affects AC-001.1).
- **A6** The list returns tasks in creation order, oldest first (other option: by due date, or newest first; affects AC-001.5).
- **A7** At most 1000 tasks are held, so that memory stays bounded on a service reachable over the network; the 1001st create answers `409` (other option: 10000 tasks, or no limit; affects AC-001.8).
- **A8** Unknown fields in the create body are ignored (other option: reject them with `422`; affects AC-001.1, AC-001.2).
- **A9** The service runs as a single instance in each environment, so that every client sees the same list; with several replicas each one would hold its own tasks (other option: shared storage, which is a later spec; affects AC-001.5).
- **A10** Creating and listing tasks needs no authentication: any caller that reaches the service may use both endpoints, in every environment; access control follows in a separate spec (other option: a shared API key header; affects AC-001.1 to AC-001.8) (decided by the user 2026-11-23).

## Open questions

- ~~Who may create and list tasks? With no authentication, anyone who can reach the service's URL in an environment can create up to 1000 tasks and read all of them. (suggested: no authentication in this spec, open to any caller, with access control as a follow-up spec; alternatives: a shared API key in a request header read from an environment variable; or restrict the feature to dev only, which limits to [dev]; affects AC-001.1 to AC-001.8)~~ Answered 2026-11-23: no authentication for now; access control in a follow-up spec (A10, Non-goals).

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-23 created
- 2026-11-23 priority P1 proposed: P1: normal bug or feature
- 2026-11-23 amended: open question on access answered (no authentication for now, A10); access control made a non-goal
- 2026-11-23 approved
- 2026-11-23 building
- 2026-11-23 done
- 2026-11-23 AC-001.7 superseded by AC-002.2
- 2026-11-23 AC-001.6 superseded by AC-002.4
