import asyncio
import logging

from star_attendance.core.utils import success
from star_attendance.db.bootstrap import apply_pending_migrations, verify_runtime_schema
from star_attendance.queueing import create_queue_pool, install_queue_schema, require_queue_schema

logger = logging.getLogger("bootstrap_db")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


async def bootstrap_database() -> None:
    executed = apply_pending_migrations()
    if executed:
        logger.info("Applied migrations: %s", ", ".join(executed))
    else:
        logger.info("No pending SQL migrations found.")

    pool = await create_queue_pool()
    try:
        installed = await install_queue_schema(pool)
        if installed:
            logger.info("Installed pgqueuer schema.")
        await require_queue_schema(pool)
    finally:
        await pool.close()

    verify_runtime_schema(require_pgqueuer=True)
    logger.info("Database bootstrap verification complete.")
    success("Star ASN System Online - Database Priming Complete", scope="BOOTSTRAP")


def main() -> None:
    asyncio.run(bootstrap_database())


if __name__ == "__main__":
    main()
