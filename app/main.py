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
from fastapi.responses import JSONResponse
import asyncio

from app.config import Settings, get_settings, validate_secrets
from app.grpc.channel import verify_cert_files
from app.auth import AuthUser, get_current_user
from app.services import get_mcp_client, shutdown_mcp_client
from app.services import get_session_manager, shutdown_session_manager
from app.services.query_processor import QueryProcessor
from app.cache import get_redis, close_redis, health_check_redis
from app.db.connection import async_engine, health_check_db
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


# Global query processor instance
_query_processor: QueryProcessor | None = None


async def get_query_processor() -> QueryProcessor:
    """Get the global query processor instance."""
    return _query_processor


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    global _query_processor

    # Validate all secrets immediately — crash loudly before any service starts
    settings = get_settings()
    validate_secrets(settings)

    # Verify TLS cert files exist before any gRPC channel is opened
    verify_cert_files()

    logger.info("Starting Client Connector service")

    # Log all configuration settings, masking secrets
    safe_settings = {
        k: (v if "secret" not in k.lower() and "key" not in k.lower() else "***")
        for k, v in settings.model_dump().items()
    }
    logger.info("Application settings", **safe_settings)
    
    # Initialize Redis connection pool
    try:
        await get_redis()
        logger.info("Redis cache initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Redis", error=str(e))
        raise

    # Verify Database connection (since engine is created at module level we just health check)
    try:
        db_ok = await health_check_db()
        if not db_ok:
            raise RuntimeError("Database health check failed")
        logger.info("Database engine initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize Database engine", error=str(e))
        raise
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
    
    # Initialize query processor for the distributed pipeline
    _query_processor = QueryProcessor(
        data_vent_url=settings.data_vent_url,
        embeddings_service_url=settings.embeddings_service_url,
        internal_secret=settings.cc_internal_secret,
    )
    await _query_processor.initialize()
    logger.info("Query processor initialized",
                data_vent=settings.data_vent_url,
                embeddings=settings.embeddings_service_url)
    
    logger.info(
        "Client Connector ready",
        host=settings.host,
        port=settings.port,
    )
    
    yield
    
    # Shutdown
    logger.info("Shutting down Client Connector")
    if _query_processor:
        await _query_processor.close()
    await shutdown_mcp_client()
    await shutdown_session_manager()
    await close_redis()
    await async_engine.dispose()
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
    
    # Query endpoint — semantic search via data-vent pipeline
    @app.post("/api/v1/query")
    async def query_knowledge(
        request: dict,
        user: AuthUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Query the knowledge base using the distributed pipeline."""
        processor = await get_query_processor()
        if not processor:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Query processor not initialized",
            )
        
        result = await processor.process_query(
            query=request.get("query", ""),
            source_ids=request.get("source_ids"),
            limit=request.get("limit", 20),
            search_type=request.get("search_type", "hybrid"),
        )
        
        return processor.format_mcp_response(result)
    
    # Health and Readiness endpoints
    @app.get("/health")
    async def get_health() -> JSONResponse:
        """Health check endpoint checking concurrent dependencies."""
        redis_ok, db_ok = await asyncio.gather(
            health_check_redis(),
            health_check_db()
        )
        
        overall_status = "ok" if (redis_ok and db_ok) else "degraded"
        status_code = 200 if overall_status == "ok" else 503
        
        return JSONResponse(
            status_code=status_code,
            content={
                "status": overall_status,
                "redis": "ok" if redis_ok else "error",
                "db": "ok" if db_ok else "error",
            }
        )
        
    @app.get("/ready")
    async def get_ready() -> JSONResponse:
        """Readiness check for K8s readinessProbe. Returns 200 if fully healthy."""
        redis_ok, db_ok = await asyncio.gather(
            health_check_redis(),
            health_check_db()
        )
        
        if not (redis_ok and db_ok):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Not fully ready"
            )
            
        return JSONResponse(status_code=200, content={"status": "ready"})
    
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
