from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from star_attendance.core.config import settings

if TYPE_CHECKING:
    pass


class DBManager:
    def __init__(self) -> None:
        self.sync_url = settings.POSTGRES_URL
        self.async_url = settings.database_url

        engine_options = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 10,
            "max_overflow": 5,
        }

        # Sync Engine (for standard operations)
        self.engine = create_engine(self.sync_url, **engine_options)
        self.SyncSession = sessionmaker(self.engine, class_=Session, expire_on_commit=False)

        # Async Engine (for PgQueuer and workers)
        self.async_engine = create_async_engine(self.async_url, **engine_options)
        self.AsyncSession = async_sessionmaker(self.async_engine, class_=AsyncSession, expire_on_commit=False)

    def create_database(self) -> None:
        """Build tables if they don't exist."""
        from star_attendance.db.models import Base

        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_session(self):
        """Sync session with automatic commit/rollback."""
        with self.SyncSession() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    @asynccontextmanager
    async def get_async_session(self):
        """Async session with automatic commit/rollback."""
        async with self.AsyncSession() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Lazy singleton — avoids import-time DB connection errors
_db_manager: DBManager | None = None


def get_db_manager() -> DBManager:
    """Get or create the DBManager singleton lazily."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DBManager()
    return _db_manager


# Module-level lazy attribute for backward compatibility
# `from star_attendance.db.manager import db_manager` will resolve lazily
def __getattr__(name: str) -> DBManager:
    if name == "db_manager":
        return get_db_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
