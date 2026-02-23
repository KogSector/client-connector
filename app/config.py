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
    mcp_server_path: str | None = Field(default=None, alias="MCP_SERVER_PATH")
    mcp_server_mode: Literal["subprocess", "http"] = Field(default="http", alias="MCP_SERVER_MODE")
    mcp_server_url: str = Field(alias="MCP_SERVER_URL")

    # Authentication
    auth_middleware_url: str = Field(
        alias="AUTH_MIDDLEWARE_GRPC_ADDR"
    )
    jwt_secret: str = Field(default="dev_secret_key", alias="JWT_SECRET")
    jwt_algorithm: str = "HS256"
    api_key_header: str = "X-API-Key"

    # Database
    database_url: str = Field(
        alias="POSTGRES_URL"
    )

    # Rate Limiting
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 10

    # Session
    session_timeout_minutes: int = 60
    max_concurrent_clients: int = 100

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Feature Toggle
    feature_toggle_url: str = Field(
        alias="FEATURE_TOGGLE_SERVICE_URL"
    )

    # CORS
    cors_origins: str = Field(
        alias="CORS_ORIGINS"
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins as list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
