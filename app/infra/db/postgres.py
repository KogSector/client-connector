import uuid
import structlog
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import func

from app.config import get_settings

logger = structlog.get_logger()

class Base(DeclarativeBase):
    pass

class Agent(Base):
    """AI Agent connection record."""
    __tablename__ = "agents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=True)
    name = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=True)
    agent_type = Column(String(100), nullable=False)
    endpoint = Column(String(500), nullable=True)
    api_key = Column(String(500), nullable=True)
    permissions = Column(JSONB, default=list)
    status = Column(String(50), default="Pending")
    config = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)
    usage_stats = Column(JSONB, default=dict)

_engine = None
_session_factory = None

async def init_postgresql() -> None:
    """Initialize PostgreSQL connection and create tables."""
    global _engine, _session_factory
    
    settings = get_settings()
    database_url = settings.database_url
    
    if not database_url:
        logger.warning("POSTGRES_URL not set, skipping database initialization")
        return

    # NeonDB requires sslmode=require, asyncpg uses ssl=True
    _engine = create_async_engine(
        database_url,
        echo=False,
        connect_args={"ssl": True} if "neon.tech" in database_url else {}
    )
    
    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    
    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("PostgreSQL initialized successfully")

async def close_postgresql() -> None:
    """Close PostgreSQL connection."""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None

def get_session() -> AsyncSession:
    """Get a database session."""
    if not _session_factory:
        raise RuntimeError("PostgreSQL not initialized")
    return _session_factory()
