"""Configuration settings for client-connector."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=(".env.map", ".env.secret"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str
    port: int = Field(alias="CLIENT_CONNECTOR_PORT")
    debug: bool

    # MCP Server
    mcp_server_path: str | None = Field(default=None, alias="MCP_SERVER_PATH")
    mcp_server_mode: Literal["subprocess", "http"] = Field(alias="MCP_SERVER_MODE")
    mcp_server_url: str = Field(alias="MCP_SERVER_URL")

    # Authentication
    auth_middleware_url: str = Field(
        alias="AUTH_MIDDLEWARE_URL"
    )
    jwt_secret: str = Field(alias="JWT_SECRET")
    jwt_algorithm: str
    api_key_header: str

    # Database
    database_url: str = Field(
        alias="POSTGRES_URL"
    )

    # Rate Limiting
    rate_limit_per_minute: int
    rate_limit_burst: int

    # Session
    session_timeout_minutes: int
    max_concurrent_clients: int

    # Logging
    log_level: str
    log_format: Literal["json", "console"]

    # Downstream Services (for MCP gateway operations)
    data_vent_url: str = Field(
        alias="DATA_VENT_URL"
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
