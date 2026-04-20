from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from star_attendance.core.config import settings
from star_attendance.db.models import Base


class DBManager:
    def __init__(self):
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
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # Async Engine (for PgQueuer and workers)
        self.async_engine = create_async_engine(self.async_url, **engine_options)
        self.AsyncSessionLocal = sessionmaker(self.async_engine, class_=AsyncSession, expire_on_commit=False)

    def create_database(self):
        """Build tables if they don't exist"""
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_session(self):
        """Sync session"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def get_async_session(self):
        """Async session"""
        async with self.AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


# Singleton instance
db_manager = DBManager()
