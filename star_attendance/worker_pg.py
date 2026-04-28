import asyncio
import logging

from pgqueuer import PgQueuer  # type: ignore

from star_attendance.core.config import settings
from star_attendance.core.logging_config import configure_structlog
from star_attendance.core.options import RuntimeOptions
from star_attendance.core.processor import process_single_user
from star_attendance.db.bootstrap import verify_runtime_schema
from star_attendance.queueing import close_queue_pool, create_queue_pool, decode_queue_payload, require_queue_schema
from star_attendance.runtime import get_store

# Logging Setup
configure_structlog(settings.LOG_LEVEL)
logger = logging.getLogger("worker_pg")


async def main():
    logger.info("Initializing Star ASN PostgreSQL Worker (Redis-Free)...")

    verify_runtime_schema(require_pgqueuer=True)
    store = get_store()
    pool = await create_queue_pool()
    queries = await require_queue_schema(pool)

    # PgQueuer expects an asyncpg/psycopg driver, not a SQLAlchemy engine.
    pq = PgQueuer.from_asyncpg_pool(pool)

    @pq.entrypoint("attendance.process")
    async def process_task(job):
        if store.is_mass_stop_requested():
            logger.warning("Task skipped due to mass stop signal.")
            return

        payload = decode_queue_payload(job.payload)
        nip = payload.get("nip")
        action = payload.get("action", "in")
        request_key = payload.get("request_key")
        source = payload.get("source", "mass_dispatch")
        logger.info(f"event=task_received nip={nip} action={action} request_key={request_key}")

        user_data = store.get_user_data(nip)
        if not user_data:
            logger.error(f"User not found in DB: {nip}")
            return

        options = RuntimeOptions.from_store(
            action=action,
            store=store,
            source=source,
            request_key=request_key,
        )
        try:
            result, _ = await process_single_user(user_data, options, 1, 1, is_mass=True)
            logger.info(f"event=task_complete nip={nip} success={result} request_key={request_key}")
            
            # Real-time UI updates
            if source == "mass_dispatch":
                store.increment_mass_pos()
                store.add_mass_log(nip, user_data.get("nama", "Unknown"), "success" if result else "failed")
                
        except Exception as e:
            logger.error(f"event=task_error nip={nip} request_key={request_key} error={e}")
            if source == "mass_dispatch":
                store.increment_mass_pos()
                store.add_mass_log(nip, user_data.get("nama", "Unknown"), "failed")

    logger.info("Worker Cluster Online. Listening for PostgreSQL notifications...")
    try:
        await pq.run()
    finally:
        await close_queue_pool()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Worker Shutdown.")
