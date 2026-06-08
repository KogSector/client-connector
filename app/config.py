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
    host: str = "0.0.0.0"  # nosec B104 - Intentional for containerized deployment
    port: int = Field(default=8095, alias="CLIENT_CONNECTOR_PORT")
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

    # Downstream Services (for MCP gateway operations)
    data_vent_url: str = Field(
        default="http://data-vent:3005",
        alias="DATA_VENT_URL"
    )



    # CORS
    cors_origins: str = Field(
        alias="CORS_ORIGINS"
    )
    
    # Kafka
    kafka_bootstrap_servers: str = Field(default="127.0.0.1:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_client_id: str = Field(default="client-connector", alias="KAFKA_CLIENT_ID")
    kafka_security_protocol: str = Field(default="PLAINTEXT", alias="KAFKA_SECURITY_PROTOCOL")
    kafka_sasl_mechanism: str | None = Field(default=None, alias="KAFKA_SASL_MECHANISM")
    kafka_sasl_username: str | None = Field(default=None, alias="KAFKA_SASL_USERNAME")
    kafka_sasl_password: str | None = Field(default=None, alias="KAFKA_SASL_PASSWORD")
    kafka_events_topic: str = Field(default="agent.events", alias="KAFKA_AGENT_EVENTS_TOPIC")

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins as list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
