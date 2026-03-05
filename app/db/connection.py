"""Database connection management for the Client Connector service."""

import contextlib
from typing import AsyncGenerator

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import Base

logger = structlog.get_logger(__name__)


def create_engine() -> AsyncEngine:
    """Create and return a new AsyncEngine.
    
    Uses connection pooling parameters suitable for an async production service.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )


# Module-level instances created at import time
async_engine: AsyncEngine = create_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@contextlib.asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a new AsyncSession.
    
    The caller is responsible for committing or rolling back the transaction.
    """
    async with AsyncSessionLocal() as session:
        yield session


async def health_check_db() -> bool:
    """Run a simple SELECT 1 to verify database connectivity.
    
    Returns
    -------
    bool
        True if the database is reachable, False otherwise.
    """
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("database_health_check_failed", error=str(e), exc_info=True)
        return False


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession.
    
    Automatically commits on successful request processing, or rolls back
    if an exception is raised in the route handler.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
