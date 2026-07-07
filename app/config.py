"""Configuration settings for client-connector."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=(".env.map", ".env.secret", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(alias="CLIENT_CONNECTOR_PORT", default=3020)
    debug: bool = Field(default=False)

    # MCP Server
    mcp_server_path: str | None = Field(default=None, alias="MCP_SERVER_PATH")
    mcp_server_mode: Literal["subprocess", "http"] = Field(alias="MCP_SERVER_MODE", default="http")
    mcp_server_url: str = Field(alias="MCP_SERVER_URL", default="http://localhost:3005")

    # Authentication
    auth_middleware_url: str = Field(alias="AUTH_MIDDLEWARE_URL")
    api_key_header: str = Field(default="X-API-Key")

    # Database
    database_url: str = Field(alias="POSTGRES_URL")

    # Rate Limiting
    rate_limit_per_minute: int = Field(default=60)
    rate_limit_burst: int = Field(default=10)

    # Session
    session_timeout_minutes: int = Field(default=60)
    max_concurrent_clients: int = Field(default=100)

    # Logging
    log_level: str = Field(default="info")
    log_format: Literal["json", "console"] = Field(default="console")

    # Downstream Services (for MCP gateway operations)
    data_vent_url: str = Field(alias="DATA_VENT_URL")

    # CORS
    cors_origins: str = Field(alias="CORS_ORIGINS")

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins as list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
