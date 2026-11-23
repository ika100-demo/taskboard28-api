# Environment variables

Configuration is read exclusively from environment variables. Defaults below are the application defaults. The deployed values are set per environment in the system's gitops-app repo (`system.yaml`: a component's `env`, and `replicas`, `resources` under `instances.<env>`).

## Core

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP port the service listens on. |
| `LOG_LEVEL` | `INFO` | Logging level. One of `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

## Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | _(unset — libpq falls back to `PG*`)_ | Postgres connection URL, read on every connection. Injected by the gitops `uses: postgres`. |
| `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` | _(unset)_ | Standard libpq variables, used when `DATABASE_URL` is unset or empty. |

Every database call connects with `connect_timeout=3` s and `statement_timeout=5000` ms; `/ready` uses 2 s and 2000 ms. A slower or unreachable database answers `503 {"detail": "task store unavailable"}`. The service applies its own schema (`schema_migrations`, `tasks`) on first connection.

## Observability

| Variable | Default | Description |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | _(unset — tracing disabled)_ | Standard OpenTelemetry endpoint, e.g. `http://otel-collector:4318`; injected by the platform's observability setting of the environment. When set, `configure_tracing()` runs at startup. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | `http/protobuf` or `grpc`. |
| `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES` | _(project name)_ | Resource attributes; set by the observability setting of the environment. |
| `OTLP_ENDPOINT` | _(unset)_ | Legacy gRPC endpoint (kept for compatibility); prefer the standard variables. |
| `METRICS_PORT` | `8080` | Port serving `/metrics` (same as the main HTTP port unless overridden). |
