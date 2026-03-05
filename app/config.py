"""Configuration settings for client-connector."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
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

    # Deployment environment — governs which dangerous runtime modes are permitted
    env: str = Field(default="production", alias="ENV")

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        allowed = {"local", "development", "staging", "production"}
        if v not in allowed:
            raise ValueError(
                f"ENV='{v}' is not a recognised environment. Must be one of: {sorted(allowed)}"
            )
        return v

    # MCP Server
    mcp_server_path: str | None = Field(default=None, alias="MCP_SERVER_PATH")
    mcp_server_mode: Literal["subprocess", "http"] = Field(default="http", alias="MCP_SERVER_MODE")
    mcp_server_url: str = Field(alias="MCP_SERVER_URL")

    # Authentication
    auth_middleware_url: str = Field(
        alias="AUTH_MIDDLEWARE_GRPC_ADDR"
    )
    jwt_secret: str = Field(alias="JWT_SECRET")

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        _BANNED = {"dev_secret_key", "changeme", "secret", "test", "development"}
        if not v or v in _BANNED:
            raise ValueError(
                "JWT_SECRET is not set or is using a known-insecure default value. "
                "Refusing to start."
            )
        return v

    jwt_algorithm: str = "HS256"
    api_key_header: str = "X-API-Key"

    # Database
    database_url: str = Field(
        alias="POSTGRES_URL"
    )
    redis_url: str

    # Observability & Audit
    otel_endpoint: str = ""
    audit_sink: str = "stdout"

    # Security (Extended)
    jwt_public_key: str
    jwt_jwks_url: str
    encryption_key_dek: str = ""
    encryption_key_audit: str = ""

    # Resiliency
    max_retry_attempts: int = 3
    circuit_breaker_threshold: int = 5
    circuit_breaker_window_seconds: int = 60
    circuit_breaker_reset_timeout: int = 30
    idempotency_ttl: int = 86400

    @model_validator(mode="after")
    def validate_model_after(self) -> "Settings":
        if self.jwt_secret == "dev_secret_key":
            raise ValueError("JWT_SECRET cannot be 'dev_secret_key'")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with 'postgresql+asyncpg://'")
        return self

    # Rate Limiting
    rate_limit_per_minute: int = 60
    rate_limit_burst: int = 10

    # Session
    session_timeout_minutes: int = 60
    max_concurrent_clients: int = 100

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Downstream Services (for query processing pipeline)
    data_vent_url: str = Field(
        default="http://data-vent:3005",
        alias="DATA_VENT_URL"
    )
    embeddings_service_url: str = Field(
        default="http://embeddings-service:3001",
        alias="EMBEDDINGS_SERVICE_URL"
    )

    # Internal service-to-service auth
    cc_internal_secret: str = Field(alias="CC_INTERNAL_SECRET")

    @field_validator("cc_internal_secret")
    @classmethod
    def validate_cc_internal_secret(cls, v: str) -> str:
        _BANNED = {"dev_secret_key", "changeme", "secret", "test", "development"}
        if not v or v in _BANNED:
            raise ValueError(
                "CC_INTERNAL_SECRET is not set or is using a known-insecure default value. "
                "Refusing to start."
            )
        return v

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


# ---------------------------------------------------------------------------
# Startup secret validation
# ---------------------------------------------------------------------------

_BANNED_SECRET_VALUES: frozenset[str] = frozenset(
    {"dev_secret_key", "changeme", "secret", "test", "development", ""}
)


def validate_secrets(settings: Settings) -> None:
    """Raise RuntimeError at startup if any secret uses a known-insecure value,
    or if a dangerous runtime mode is requested in the wrong environment.

    Call this as the very first thing inside the FastAPI lifespan so the
    process crashes immediately with a clear message rather than silently
    serving traffic with a compromised secret.
    """
    if not settings.jwt_secret or settings.jwt_secret in _BANNED_SECRET_VALUES:
        raise RuntimeError(
            "FATAL: JWT_SECRET is not set or is using a known-insecure default value. "
            "Set a strong, randomly-generated secret before starting the server."
        )
    if not settings.cc_internal_secret or settings.cc_internal_secret in _BANNED_SECRET_VALUES:
        raise RuntimeError(
            "FATAL: CC_INTERNAL_SECRET is not set or is using a known-insecure default value. "
            "Set a strong, randomly-generated secret before starting the server."
        )
    if settings.mcp_server_mode == "subprocess" and settings.env != "local":
        raise RuntimeError(
            f"FATAL: MCP subprocess mode is forbidden in ENV={settings.env!r}. "
            "Subprocess mode is only allowed when ENV=local."
        )
