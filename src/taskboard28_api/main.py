"""FastAPI entry point for taskboard28-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__, db
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import router as tasks_router
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply the schema at startup; an unreachable database defers it, never exits."""
    try:
        await run_in_threadpool(db.ensure_schema)
    except db.TaskStoreUnavailableError:
        logger.warning("db_schema_deferred")
    yield


app = FastAPI(title="taskboard28-api", version=__version__, lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
app.include_router(tasks_router)
if tracing_enabled():
    FastAPIInstrumentor.instrument_app(app)


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse | JSONResponse:
    """Readiness probe — 200 while the database answers, else 503."""
    if db.check_ready():
        return HealthResponse(status="ready")
    return JSONResponse(status_code=503, content={"detail": "task store unavailable"})


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "taskboard28-api"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
