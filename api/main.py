import asyncio
import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.scheduler import AttendanceScheduler
from star_attendance.core.config import settings
from star_attendance.core.exceptions import (
    AuthenticationError,
    BusinessLogicError,
    DatabaseError,
    ExternalServiceError,
    QueueError,
    StarAsnError,
    UserNotFoundError,
    ValidationError,
)
from star_attendance.db.bootstrap import apply_pending_migrations, verify_runtime_schema
from star_attendance.runtime import get_store

if TYPE_CHECKING:
    from asyncpg import Connection

from star_attendance.core.logging_config import configure_structlog
from star_attendance.core.tracing import instrument_fastapi, instrument_httpx, instrument_asyncpg, setup_tracing

configure_structlog(settings.LOG_LEVEL)
setup_tracing(service_name="star-asn-api")
logger = logging.getLogger("api")

store = get_store()
scheduler = AttendanceScheduler(store)


# --- REAL-TIME SYNC LISTENER ---
async def listen_to_db_notifications():
    """
    Listens for 'scheduler_sync_trigger' from Postgres and syncs the scheduler immediately.
    Ensures that the last change is always captured with a trailing sync.
    """
    sync_pending = False
    sync_lock = asyncio.Lock()

    async def do_sync():
        nonlocal sync_pending
        async with sync_lock:
            if sync_pending:
                return
            sync_pending = True

        # Wait a bit to collect multiple rapid changes (debounce)
        await asyncio.sleep(2.0)

        logger.info("Processing real-time DB notification. Invalidating cache and syncing scheduler...")
        try:
            # 1. Force invalidate all caches to get fresh data from DB
            store.invalidate_all_caches()

            # 2. Sync the scheduler with fresh data
            await scheduler.sync_user_schedules()
        except Exception as exc:
            logger.error("Failed to sync scheduler from notification: %s", exc, exc_info=True)
        finally:
            async with sync_lock:
                sync_pending = False

    while True:
        conn = None
        try:
            conn = await asyncpg.connect(settings.POSTGRES_URL, statement_cache_size=0)
            # Add listener to the connection. Using lambda to ensure it runs as a non-blocking task.
            await conn.add_listener("scheduler_sync_trigger", lambda *args: asyncio.create_task(do_sync()))
            logger.info("Real-time sync listener connected to database.")

            # Keep the connection alive
            while True:
                await asyncio.sleep(60)
                await conn.execute("SELECT 1")  # Heartbeat
        except Exception as exc:
            logger.error("Real-time sync listener error: %s. Retrying in 5s...", exc, exc_info=True)
            if conn:
                try:
                    await conn.close()
                except Exception as close_exc:
                    logger.debug("Failed to close connection during cleanup: %s", close_exc)
            await asyncio.sleep(5)


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token,
        settings.resolved_internal_api_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    apply_pending_migrations()
    verify_runtime_schema(require_pgqueuer=True)
    # Start the background listener for real-time DB changes
    asyncio.create_task(listen_to_db_notifications())
    await scheduler.start()
    yield


app = FastAPI(
    title="Star ASN Internal API",
    version="5.0.0",
    lifespan=lifespan,
)

# OpenTelemetry instrumentation
instrument_fastapi(app)
instrument_httpx()
instrument_asyncpg()


# --- PYDANTIC RESPONSE MODELS ---


class HealthzResponse(BaseModel):
    status: str
    database: str
    scheduler_running: bool
    scheduler_jobs: int
    queue_table_ready: bool


class SchedulerStatusResponse(BaseModel):
    running: bool
    timezone: str
    job_count: int
    jobs: list[dict[str, str]]


class SyncResponse(BaseModel):
    status: str
    job_count: int


class RestartResponse(BaseModel):
    status: str
    running: bool
    timezone: str
    job_count: int
    jobs: list[dict[str, str]]


class TriggerResponse(BaseModel):
    status: str
    nip: str
    message: str


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
    nip: str | None = None


# --- GLOBAL EXCEPTION HANDLERS ---


@app.exception_handler(StarAsnError)
async def star_asn_error_handler(request: Request, exc: StarAsnError) -> JSONResponse:
    """Handle all StarAsn domain errors with structured responses."""
    status_code = 500
    if isinstance(exc, UserNotFoundError):
        status_code = 404
    elif isinstance(exc, (ValidationError, BusinessLogicError)):
        status_code = 422
    elif isinstance(exc, AuthenticationError):
        status_code = 401
    elif isinstance(exc, DatabaseError):
        status_code = 503
    elif isinstance(exc, (QueueError, ExternalServiceError)):
        status_code = 503

    return JSONResponse(
        status_code=status_code,
        content={"error": exc.message, "detail": str(exc.details) if exc.details else None},
    )


@asynccontextmanager
async def get_db_connection() -> AsyncGenerator[Connection, None]:
    """Get a database connection with proper cleanup."""
    conn: Connection | None = None
    try:
        conn = await asyncpg.connect(settings.POSTGRES_URL, statement_cache_size=0)
        yield conn
    except Exception as exc:
        raise DatabaseError(f"Failed to connect to database: {exc}") from exc
    finally:
        if conn is not None:
            await conn.close()


@app.get("/healthz", dependencies=[Depends(require_internal_token)], response_model=HealthzResponse)
async def healthz() -> HealthzResponse:
    """Health check endpoint with detailed status information."""
    try:
        verify_runtime_schema(require_pgqueuer=True)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "degraded",
                "database": "schema_error",
                "error": f"Schema validation failed: {exc}",
                "scheduler_running": scheduler.scheduler.running,
            },
        ) from exc

    async with get_db_connection() as conn:
        try:
            await conn.fetchval("SELECT 1")
            queue_table_ready = await conn.fetchval("SELECT to_regclass('public.pgqueuer') IS NOT NULL")
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "degraded",
                    "database": "connection_error",
                    "error": f"Database query failed: {exc}",
                    "scheduler_running": scheduler.is_running,
                },
            ) from exc

    status_data = await scheduler.get_status_async()
    return HealthzResponse(
        status="ok",
        database="ok",
        scheduler_running=status_data["running"],
        scheduler_jobs=status_data["job_count"],
        queue_table_ready=bool(queue_table_ready),
    )


@app.get("/internal/scheduler/status", dependencies=[Depends(require_internal_token)], response_model=SchedulerStatusResponse)
async def scheduler_status() -> SchedulerStatusResponse:
    """Get current scheduler status and job list."""
    data = await scheduler.get_status_async()
    return SchedulerStatusResponse(**data)


@app.post("/internal/scheduler/sync", dependencies=[Depends(require_internal_token)], response_model=SyncResponse)
async def sync_scheduler() -> SyncResponse:
    """Manually trigger scheduler synchronization."""
    await scheduler.sync_user_schedules()
    status_data = await scheduler.get_status_async()
    return SyncResponse(status="sync_complete", job_count=status_data["job_count"])


@app.post("/internal/scheduler/restart", dependencies=[Depends(require_internal_token)], response_model=RestartResponse)
async def restart_scheduler() -> RestartResponse:
    """Restart the scheduler and re-sync all user schedules."""
    status_payload = await scheduler.restart()
    return RestartResponse(status="restarted", **status_payload)


# --- PUBLIC API FOR DASHBOARD (Mini App) ---


@app.post("/api/attendance/trigger", response_model=TriggerResponse)
async def trigger_manual_attendance(nip: str) -> TriggerResponse:
    """
    Triggers an immediate manual attendance job for a specific NIP.
    This injects a high-priority task into pgqueuer.
    """
    logger.info("Manual attendance trigger received for NIP: %s", nip)

    # In a real enterprise setup, we should validate the Telegram InitData here.
    # For now, we'll queue the job directly to the engine.
    from star_attendance.queueing import enqueue_presence_task

    try:
        await enqueue_presence_task(nip=nip, is_manual=True)
        return TriggerResponse(status="queued", nip=nip, message=f"Task manual untuk {nip} telah masuk antrean.")
    except UserNotFoundError as exc:
        logger.warning("Manual attendance failed - user not found: %s", nip)
        raise HTTPException(
            status_code=404,
            detail={"error": "User not found", "nip": nip, "message": str(exc)}
        ) from exc
    except QueueError as exc:
        logger.error("Failed to enqueue manual task for %s: %s", nip, exc)
        raise HTTPException(
            status_code=503,
            detail={"error": "Queue unavailable", "nip": nip, "message": str(exc)}
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error enqueuing manual task for %s", nip)
        raise HTTPException(
            status_code=500,
            detail={"error": "Internal server error", "nip": nip, "message": "Failed to queue attendance task"}
        ) from exc


def resolve_bind_host(api_url: str) -> str:
    hostname = urlparse(api_url).hostname
    if hostname in {None, "127.0.0.1", "localhost", "0.0.0.0"}:
        return hostname or "127.0.0.1"
    return "0.0.0.0"


def start_api() -> None:
    api_url = settings.INTERNAL_API_URL
    parsed_url = urlparse(api_url)
    host = resolve_bind_host(api_url)
    port = parsed_url.port or 8000

    import uvicorn

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_api()
