import json
from typing import Any

import asyncpg  # type: ignore
from pgqueuer import Queries

from star_attendance.core.config import settings

_pool: asyncpg.Pool | None = None


async def get_queue_pool() -> asyncpg.Pool:
    """Get or create the shared asyncpg connection pool for queue operations.

    Reuses a single global pool instead of creating a new one per call,
    preventing connection leaks and reducing overhead.
    """
    global _pool
    if _pool is None or _pool._closed:
        _pool = await asyncpg.create_pool(
            dsn=settings.POSTGRES_URL,
            min_size=5,
            max_size=20,
            max_inactive_connection_lifetime=60,
            command_timeout=15,
            statement_cache_size=0,
        )
    return _pool


async def close_queue_pool() -> None:
    """Gracefully close the shared queue pool (for shutdown)."""
    global _pool
    if _pool is not None and not _pool._closed:
        await _pool.close()
        _pool = None


# Backward-compatible alias
async def create_queue_pool() -> asyncpg.Pool:
    """Deprecated: Use get_queue_pool() instead. Kept for backward compatibility."""
    return await get_queue_pool()


async def install_queue_schema(pool: asyncpg.Pool) -> bool:
    queries = Queries.from_asyncpg_pool(pool)
    if not await queries.has_table(queries.qbe.settings.queue_table):
        await queries.install()
        return True
    return False


async def require_queue_schema(pool: asyncpg.Pool) -> Queries:
    queries = Queries.from_asyncpg_pool(pool)
    if not await queries.has_table(queries.qbe.settings.queue_table):
        raise RuntimeError("pgqueuer schema is missing. Run the bootstrap service before runtime.")
    return queries


def encode_queue_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def decode_queue_payload(raw_payload: Any) -> dict[str, Any]:
    if raw_payload is None:
        return {}
    if isinstance(raw_payload, memoryview):
        raw_payload = raw_payload.tobytes()
    if isinstance(raw_payload, (bytes, bytearray)):
        return json.loads(bytes(raw_payload).decode("utf-8"))
    if isinstance(raw_payload, str):
        return json.loads(raw_payload)
    if isinstance(raw_payload, dict):
        return raw_payload
    raise TypeError(f"Unsupported queue payload type: {type(raw_payload)!r}")


async def enqueue_presence_task(nip: str, is_manual: bool = False, action: str = "in") -> None:
    """
    Enqueues an attendance task to pgqueuer using the shared connection pool.
    """
    pool = await get_queue_pool()
    queries = Queries.from_asyncpg_pool(pool)
    payload = {
        "nip": nip,
        "action": action,
        "source": "manual_api" if is_manual else "scheduler_auto"
    }
    await queries.enqueue(
        ["attendance.process"],
        [encode_queue_payload(payload)],
        [0]
    )
