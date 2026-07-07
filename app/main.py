"""Client Connector — MCP endpoint for AI agents.

Hosts MCP connections from AI agents (Cursor, Claude, Windsurf, etc.)
and routes knowledge queries to data-vent for FalkorDB retrieval.
"""

from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import structlog
from fastapi import Depends, FastAPI, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import AuthUser, get_current_user
from app.config import get_settings
from app.infra.db.postgres import close_postgresql, init_postgresql
from app.services import get_session_manager, shutdown_session_manager

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("Starting Client Connector service")

    # Initialize database
    await init_postgresql()

    # Start session manager
    await get_session_manager()
    logger.info("Session manager started")

    settings = get_settings()
    logger.info(
        "Client Connector ready",
        host=settings.host,
        port=settings.port,
    )

    yield

    logger.info("Shutting down Client Connector")
    await shutdown_session_manager()
    await close_postgresql()
    logger.info("Client Connector stopped")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to extract or generate a correlation ID and bind it to structlog."""
    async def dispatch(self, request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or str(uuid4())
        
        # Bind it to structlog's thread-local/async context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Client Connector",
        description="MCP endpoint for AI Agents — connects to ConFuse knowledge layer",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Correlation ID
    app.add_middleware(CorrelationIdMiddleware)

    # Mount routers
    from app.mcp_server import get_mcp_app

    # Using a versioned, fixed API endpoint for MCP
    app.mount("/api/v1/mcp", get_mcp_app().sse_app())

    # Root endpoint for UptimeRobot
    @app.api_route("/", methods=["GET", "HEAD"])
    async def root_check() -> dict[str, str]:
        """Root endpoint for basic health monitoring."""
        return {"status": "ok"}

    # Health endpoint
    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        session_manager = await get_session_manager()
        stats = await session_manager.get_stats()

        return {
            "status": "healthy",
            "service": "client-connector",
            "sessions": stats,
        }

    # Admin endpoints
    @app.get("/admin/sessions")
    async def list_sessions(
        user: AuthUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        """List all active sessions (admin only)."""
        if not user.has_role("admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required",
            )

        session_manager = await get_session_manager()
        sessions = await session_manager.list_sessions()

        return {
            "sessions": [
                {
                    "id": str(s.id),
                    "state": s.state.value,
                    "client": s.client_info.model_dump() if s.client_info else None,
                    "user_id": s.user_id,
                    "connected_at": s.connected_at.isoformat(),
                    "last_activity": s.last_activity.isoformat(),
                    "request_count": s.request_count,
                }
                for s in sessions
            ],
            "total": len(sessions),
        }

    @app.get("/admin/stats")
    async def get_stats(
        user: AuthUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Get service statistics (admin only)."""
        if not user.has_role("admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin role required",
            )

        session_manager = await get_session_manager()
        return await session_manager.get_stats()

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
