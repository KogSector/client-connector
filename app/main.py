"""Client Connector - MCP Gateway for AI Agents.

This service hosts MCP connections from AI agents (Cursor, Claude, etc.)
and proxies requests to the mcp-server (Rust) which handles the actual
MCP protocol and connectors.
"""

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.auth import AuthUser, get_current_user
from app.services import get_mcp_client, shutdown_mcp_client
from app.services import get_session_manager, shutdown_session_manager
from app.api import websocket_router

# Configure structured logging
structlog.configure(
    processors=[
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
    
    # Initialize services
    settings = get_settings()
    
    # Start MCP client (connects to/spawns mcp-server)
    try:
        mcp_client = await get_mcp_client()
        logger.info(
            "MCP client started",
            mode=settings.mcp_server_mode,
            running=mcp_client.is_running,
        )
    except Exception as e:
        logger.error("Failed to start MCP client", error=str(e))
        # Continue anyway - will fail on first request
    
    # Start session manager
    await get_session_manager()
    logger.info("Session manager started")
    
    logger.info(
        "Client Connector ready",
        host=settings.host,
        port=settings.port,
    )
    
    yield
    
    # Shutdown
    logger.info("Shutting down Client Connector")
    await shutdown_mcp_client()
    await shutdown_session_manager()
    logger.info("Client Connector stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Client Connector",
        description="MCP Gateway for AI Agents - Connects agents to ConHub knowledge layer",
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
    
    # Mount routers
    app.include_router(websocket_router, prefix="/mcp", tags=["MCP"])
    
    # Health endpoint
    @app.get("/health")
    async def health_check() -> dict[str, Any]:
        """Health check endpoint."""
        mcp_client = await get_mcp_client()
        session_manager = await get_session_manager()
        stats = await session_manager.get_stats()
        
        return {
            "status": "healthy",
            "service": "client-connector",
            "mcp_server": {
                "mode": settings.mcp_server_mode,
                "running": mcp_client.is_running,
            },
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
