"""Session manager for tracking connected clients."""

import asyncio
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import structlog
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas import ClientInfo, ConnectionState

logger = structlog.get_logger()


class ClientSession(BaseModel):
    """Represents a connected client session."""

    id: UUID = Field(default_factory=uuid4)
    client_info: ClientInfo | None = None
    state: ConnectionState = ConnectionState.CONNECTING
    connected_at: datetime = Field(default_factory=datetime.utcnow)
    last_activity: datetime = Field(default_factory=datetime.utcnow)
    request_count: int = 0
    user_id: str | None = None
    api_key_id: str | None = None
    tenant_id: str | None = None  # Multi-tenant support
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    def touch(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.utcnow()
        self.request_count += 1

    def is_expired(self, timeout_minutes: int) -> bool:
        """Check if session has expired."""
        expiry = self.last_activity + timedelta(minutes=timeout_minutes)
        return datetime.utcnow() > expiry

    def get_context(self) -> dict[str, Any]:
        """Get context for MCP requests (used for multi-tenant routing)."""
        return {
            "session_id": str(self.id),
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "api_key_id": self.api_key_id,
        }


class SessionManager:
    """Manages active client sessions."""

    def __init__(self):
        self.settings = get_settings()
        self._sessions: dict[UUID, ClientSession] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start session manager and cleanup task."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session manager started")

    async def stop(self) -> None:
        """Stop session manager."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Session manager stopped")

    async def create_session(
        self,
        user_id: str | None = None,
        api_key_id: str | None = None,
        tenant_id: str | None = None,
    ) -> ClientSession:
        """Create a new client session."""
        async with self._lock:
            if len(self._sessions) >= self.settings.max_concurrent_clients:
                raise RuntimeError("Maximum concurrent clients reached")

            session = ClientSession(
                user_id=user_id,
                api_key_id=api_key_id,
                tenant_id=tenant_id,
            )
            self._sessions[session.id] = session
            
            logger.info(
                "Session created",
                session_id=str(session.id),
                user_id=user_id,
                tenant_id=tenant_id,
            )
            return session

    async def get_session(self, session_id: UUID) -> ClientSession | None:
        """Get a session by ID."""
        return self._sessions.get(session_id)

    async def update_session(
        self,
        session_id: UUID,
        state: ConnectionState | None = None,
        client_info: ClientInfo | None = None,
    ) -> ClientSession | None:
        """Update session state."""
        session = self._sessions.get(session_id)
        if session:
            if state:
                session.state = state
            if client_info:
                session.client_info = client_info
            session.touch()
            logger.debug(
                "Session updated",
                session_id=str(session_id),
                state=session.state,
            )
        return session

    async def remove_session(self, session_id: UUID) -> None:
        """Remove a session."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info("Session removed", session_id=str(session_id))

    async def list_sessions(self) -> list[ClientSession]:
        """List all active sessions."""
        return list(self._sessions.values())

    async def get_stats(self) -> dict[str, Any]:
        """Get session statistics."""
        sessions = list(self._sessions.values())
        return {
            "total_sessions": len(sessions),
            "max_sessions": self.settings.max_concurrent_clients,
            "states": {
                state.value: sum(1 for s in sessions if s.state == state)
                for state in ConnectionState
            },
            "total_requests": sum(s.request_count for s in sessions),
        }

    async def _cleanup_loop(self) -> None:
        """Periodically cleanup expired sessions."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Session cleanup error", error=str(e))

    async def _cleanup_expired(self) -> None:
        """Remove expired sessions."""
        expired = []
        for session_id, session in self._sessions.items():
            if session.is_expired(self.settings.session_timeout_minutes):
                expired.append(session_id)

        for session_id in expired:
            await self.remove_session(session_id)

        if expired:
            logger.info("Cleaned up expired sessions", count=len(expired))


# Global singleton
_session_manager: SessionManager | None = None


async def get_session_manager() -> SessionManager:
    """Get or create session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
        await _session_manager.start()
    return _session_manager


async def shutdown_session_manager() -> None:
    """Shutdown session manager."""
    global _session_manager
    if _session_manager:
        await _session_manager.stop()
        _session_manager = None
