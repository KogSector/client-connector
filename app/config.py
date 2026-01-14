"""Configuration settings for client-connector."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = "0.0.0.0"  # nosec B104 - Intentional for containerized deployment
    port: int = 8095
    debug: bool = False

    # MCP Server
    mcp_server_path: str = "../mcp-server/target/release/mcp-service.exe"
    mcp_server_mode: Literal["subprocess", "http"] = "subprocess"
    mcp_server_url: str = "http://localhost:3004"

    # Authentication
    auth_middleware_url: str = "http://localhost:3001"
    jwt_secret: str = Field(default="change-me-in-production")
    jwt_algorithm: str = "HS256"
    api_key_header: str = "X-API-Key"

    # Database
    database_url: str = "postgresql+asyncpg://conhub:conhub_password@localhost:5432/conhub"

    # Rate Limiting
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 10

    # Session
    session_timeout_minutes: int = 60
    max_concurrent_clients: int = 100

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins as list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
