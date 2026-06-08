"""Shared configuration base for all ConFuse services."""

from functools import lru_cache
from typing import Literal, Optional
from abc import ABC, abstractmethod

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseConFuseSettings(BaseSettings, ABC):
    """Base configuration for all ConFuse services."""
    
    model_config = SettingsConfigDict(
        env_file=(".env.map", ".env.secret"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Common service configuration
    service_name: str = Field(description="Service identifier")
    host: str = Field(default="0.0.0.0", alias="HOST")  # nosec B104 - Intentional for containerized deployment
    port: int = Field(alias="APP_PORT")
    debug: bool = Field(default=False, alias="DEBUG")
    
    # Common service URLs
    auth_middleware_url: str = Field(default="http://localhost:8083", alias="AUTH_MIDDLEWARE_URL")
    unified_processor_url: str = Field(default="http://localhost:8090", alias="UNIFIED_PROCESSOR_URL")
    embeddings_service_url: str = Field(default="http://localhost:8091", alias="EMBEDDINGS_SERVICE_URL")
    relation_graph_url: str = Field(default="http://localhost:8092", alias="RELATION_GRAPH_URL")
    
    # Common timeouts
    http_timeout: float = Field(default=30.0, alias="HTTP_TIMEOUT")
    grpc_timeout: float = Field(default=10.0, alias="GRPC_TIMEOUT")
    
    # Common logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")
    
    @abstractmethod
    def get_service_specific_config(self) -> dict:
        """Get service-specific configuration overrides."""
        pass


class DataConnectorSettings(BaseConFuseSettings):
    """Data Connector specific settings."""
    
    service_name: str = "data-connector"
    port: int = Field(default=8081, alias="APP_PORT")
    
    # gRPC configuration
    grpc_port: int = Field(default=50052, alias="GRPC_PORT")
    grpc_host: str = Field(default="0.0.0.0", alias="GRPC_HOST")
    
    # Database configuration
    database_url: str = Field(alias="DATABASE_URL")
    
    # OAuth credentials
    github_client_id: str = Field(alias="GITHUB_CLIENT_ID")
    github_client_secret: str = Field(alias="GITHUB_CLIENT_SECRET")
    gitlab_client_id: str = Field(alias="GITLAB_CLIENT_ID")
    gitlab_client_secret: str = Field(alias="GITLAB_CLIENT_SECRET")
    bitbucket_client_id: str = Field(alias="BITBUCKET_CLIENT_ID")
    bitbucket_client_secret: str = Field(alias="BITBUCKET_CLIENT_SECRET")
    
    # Webhook secrets
    github_webhook_secret: str = Field(alias="GITHUB_WEBHOOK_SECRET")
    gitlab_webhook_secret: str = Field(alias="GITLAB_WEBHOOK_SECRET")
    
    # Downloads configuration
    downloads_base_path: str = Field(default="/shared/downloads", alias="DOWNLOADS_BASE_PATH")
    
    # Internal API key
    internal_api_key: str = Field(alias="INTERNAL_API_KEY")
    
    def get_service_specific_config(self) -> dict:
        return {
            "grpc_enabled": True,
            "oauth_providers": ["github", "gitlab", "bitbucket"],
            "webhook_support": True,
        }


class ClientConnectorSettings(BaseConFuseSettings):
    """Client Connector specific settings."""
    
    service_name: str = "client-connector"
    port: int = Field(default=8095, alias="APP_PORT")
    
    # MCP Server configuration
    mcp_server_path: Optional[str] = Field(default=None, alias="MCP_SERVER_PATH")
    mcp_server_mode: Literal["subprocess", "http"] = Field(default="http", alias="MCP_SERVER_MODE")
    mcp_server_url: str = Field(alias="MCP_SERVER_URL")
    
    # Authentication
    auth_required: bool = Field(default=True, alias="AUTH_REQUIRED")
    jwt_secret: str = Field(alias="JWT_SECRET")
    
    def get_service_specific_config(self) -> dict:
        return {
            "mcp_enabled": True,
            "auth_required": self.auth_required,
            "websocket_support": True,
        }


class UnifiedProcessorSettings(BaseConFuseSettings):
    """Unified Processor specific settings."""
    
    service_name: str = "unified-processor"
    port: int = Field(default=8090, alias="APP_PORT")
    
    # gRPC configuration
    grpc_port: int = Field(default=50051, alias="GRPC_PORT")
    grpc_host: str = Field(default="0.0.0.0", alias="GRPC_HOST")
    
    # Processing configuration
    max_file_size_mb: int = Field(default=100, alias="MAX_FILE_SIZE_MB")
    chunk_size: int = Field(default=1000, alias="CHUNK_SIZE")
    max_concurrent_processes: int = Field(default=10, alias="MAX_CONCURRENT_PROCESSES")
    
    # Storage
    chunks_directory: str = Field(default="./chunks", alias="CHUNKS_DIRECTORY")
    
    def get_service_specific_config(self) -> dict:
        return {
            "grpc_enabled": True,
            "file_processing": True,
            "chunking_enabled": True,
        }


@lru_cache
def get_settings(service_type: str) -> BaseConFuseSettings:
    """Get settings for specific service type."""
    settings_map = {
        "data-connector": DataConnectorSettings,
        "client-connector": ClientConnectorSettings,
        "unified-processor": UnifiedProcessorSettings,
    }
    
    settings_class = settings_map.get(service_type)
    if not settings_class:
        raise ValueError(f"Unknown service type: {service_type}")
    
    return settings_class()
