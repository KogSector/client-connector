"""Shared FastAPI application base for all ConFuse services."""

import asyncio
import structlog
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from functools import partial
from dotenv import load_dotenv

from abc import ABC, abstractmethod


class BaseConFuseApp(ABC):
    """Base FastAPI application for all ConFuse services."""
    
    def __init__(self):
        self.app: FastAPI = None
        self.logger = structlog.get_logger()
        self._load_environment()
        self._setup_logging()
    
    def _load_environment(self):
        """Load environment variables from .env files."""
        load_dotenv('.env.map')
        load_dotenv('.env.secret', override=True)
    
    def _setup_logging(self):
        """Setup structured logging."""
        # Can be overridden by specific services
        pass
    
    @abstractmethod
    def get_settings(self):
        """Get service-specific settings."""
        pass
    
    @abstractmethod
    def get_routers(self) -> List:
        """Get service-specific routers."""
        pass
    
    @abstractmethod
    async def initialize_services(self):
        """Initialize service-specific components."""
        pass
    
    @abstractmethod
    async def cleanup_services(self):
        """Cleanup service-specific components."""
        pass
    
    def setup_cors(self, app: FastAPI):
        """Setup CORS middleware."""
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Configure appropriately for production
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    def setup_middleware(self, app: FastAPI):
        """Setup service-specific middleware."""
        # Can be overridden by specific services
        pass
    
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        """Application lifespan manager."""
        settings = self.get_settings()
        
        self.logger.info(
            f"Starting {settings.service_name} service",
            port=settings.port,
            debug=settings.debug
        )
        
        try:
            # Initialize services
            await self.initialize_services()
            
            yield
            
        finally:
            self.logger.info(f"Shutting down {settings.service_name} service")
            await self.cleanup_services()
    
    def create_app(self) -> FastAPI:
        """Create and configure FastAPI application."""
        settings = self.get_settings()
        
        app = FastAPI(
            title=f"ConFuse {settings.service_name.title()}",
            description=f"ConFuse {settings.service_name} API",
            version="2.0.0",
            debug=settings.debug,
            lifespan=partial(self.lifespan, app),
        )
        
        # Setup middleware
        self.setup_cors(app)
        self.setup_middleware(app)
        
        # Add routers
        routers = self.get_routers()
        for router in routers:
            app.include_router(router)
        
        # Add health check endpoint
        self._add_health_endpoint(app)
        
        return app
    
    def _add_health_endpoint(self, app: FastAPI):
        """Add common health check endpoint."""
        @app.get("/health")
        async def health_check():
            settings = self.get_settings()
            return {
                "status": "healthy",
                "service": settings.service_name,
                "version": "2.0.0",
                "timestamp": structlog.get_logger().bind().info().timestamp
            }


class BaseServiceApp(BaseConFuseApp):
    """Base for services that need database and external service connections."""
    
    def __init__(self):
        super().__init__()
        self._db_connections = []
        self._external_clients = []
    
    async def initialize_services(self):
        """Initialize database and external service connections."""
        await self._init_database()
        await self._init_external_services()
    
    async def cleanup_services(self):
        """Cleanup database and external service connections."""
        await self._cleanup_external_services()
        await self._cleanup_database()
    
    @abstractmethod
    async def _init_database(self):
        """Initialize database connection."""
        pass
    
    @abstractmethod
    async def _init_external_services(self):
        """Initialize external service connections."""
        pass
    
    @abstractmethod
    async def _cleanup_database(self):
        """Cleanup database connection."""
        pass
    
    @abstractmethod
    async def _cleanup_external_services(self):
        """Cleanup external service connections."""
        pass
    
    def add_db_connection(self, connection):
        """Add database connection to cleanup list."""
        self._db_connections.append(connection)
    
    def add_external_client(self, client):
        """Add external client to cleanup list."""
        self._external_clients.append(client)


def create_service_app(service_class) -> FastAPI:
    """Factory function to create service application."""
    service = service_class()
    return service.create_app()
