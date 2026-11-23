# Architecture decision records

| ADR | Decision |
|---|---|
| [001](001-postgres-task-store.md) | Tasks are stored in Postgres via psycopg 3, one connection per call, schema applied by the service at start from an ordered migration list |
