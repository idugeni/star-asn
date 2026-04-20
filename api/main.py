import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import asyncpg  # type: ignore
from fastapi import Depends, FastAPI, Header, HTTPException, status

from api.scheduler import AttendanceScheduler
from star_attendance.core.config import settings
from star_attendance.db.bootstrap import verify_runtime_schema
from star_attendance.runtime import get_store

logger = logging.getLogger("api")
logger.setLevel(getattr(logging, settings.LOG_LEVEL))

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
            logger.error(f"Failed to sync scheduler from notification: {exc}")
        finally:
            async with sync_lock:
                sync_pending = False

    while True:
        conn = None
        try:
            conn = await asyncpg.connect(settings.POSTGRES_URL)
            # Add listener to the connection. Using lambda to ensure it runs as a non-blocking task.
            await conn.add_listener('scheduler_sync_trigger', lambda *args: asyncio.create_task(do_sync()))
            logger.info("Real-time sync listener connected to database.")
            
            # Keep the connection alive
            while True:
                await asyncio.sleep(60)
                await conn.execute("SELECT 1") # Heartbeat
        except Exception as exc:
            logger.error(f"Real-time sync listener error: {exc}. Retrying in 5s...")
            if conn:
                try: await conn.close()
                except: pass
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


@app.get("/healthz", dependencies=[Depends(require_internal_token)])
async def healthz():
    conn = None
    try:
        verify_runtime_schema(require_pgqueuer=True)
        conn = await asyncpg.connect(settings.POSTGRES_URL)
        await conn.fetchval("SELECT 1")
        queue_table_ready = await conn.fetchval("SELECT to_regclass('public.pgqueuer') IS NOT NULL")
        return {
            "status": "ok",
            "database": "ok",
            "scheduler_running": scheduler.scheduler.running,
            "scheduler_jobs": len(scheduler.get_jobs()),
            "queue_table_ready": bool(queue_table_ready),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "degraded",
                "database": "error",
                "error": str(exc),
                "scheduler_running": scheduler.scheduler.running,
            },
        ) from exc
    finally:
        if conn is not None:
            await conn.close()


@app.get("/internal/scheduler/status", dependencies=[Depends(require_internal_token)])
async def scheduler_status():
    return scheduler.get_status()


@app.post("/internal/scheduler/sync", dependencies=[Depends(require_internal_token)])
async def sync_scheduler():
    await scheduler.sync_user_schedules()
    return {"status": "sync_complete", "job_count": len(scheduler.get_jobs())}


@app.post("/internal/scheduler/restart", dependencies=[Depends(require_internal_token)])
async def restart_scheduler():
    status_payload = await scheduler.restart()
    return {"status": "restarted", **status_payload}


# --- PUBLIC API FOR DASHBOARD (Mini App) ---

@app.post("/api/attendance/trigger")
async def trigger_manual_attendance(nip: str):
    """
    Triggers an immediate manual attendance job for a specific NIP.
    This injects a high-priority task into pgqueuer.
    """
    logger.info(f"Manual attendance trigger received for NIP: {nip}")
    
    # In a real enterprise setup, we should validate the Telegram InitData here.
    # For now, we'll queue the job directly to the engine.
    from star_attendance.queueing import enqueue_presence_task
    
    try:
        await enqueue_presence_task(nip=nip, is_manual=True)
        return {"status": "queued", "nip": nip, "message": f"Task manual untuk {nip} telah masuk antrean."}
    except Exception as e:
        logger.error(f"Failed to enqueue manual task: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
