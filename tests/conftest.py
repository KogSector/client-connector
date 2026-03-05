"""
Top-level pytest configuration for client-connector.

Sets valid environment variables BEFORE any app module is imported so that:
  - module-level calls to get_settings() succeed,
  - SQLAlchemy create_async_engine() receives a syntactically valid URL.

The engine call itself is also mocked so no asyncpg driver is required.
"""

import os
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# 1. Environment — must happen before any app import
# ---------------------------------------------------------------------------

_GOOD_ENV = {
    "POSTGRES_URL": "postgresql+asyncpg://cc:cc@localhost:5432/cc",
    "REDIS_URL": "redis://localhost:6379/0",
    "JWT_SECRET": "super-secret-jwt-value-not-guessable",
    "JWT_PUBLIC_KEY": "test-public-key",
    "JWT_JWKS_URL": "http://auth/.well-known/jwks.json",
    "CC_INTERNAL_SECRET": "super-secret-internal-value",
    "MCP_SERVER_URL": "http://mcp-server:8080",
    "AUTH_MIDDLEWARE_GRPC_ADDR": "auth-middleware:50051",
    "FEATURE_TOGGLE_SERVICE_URL": "http://feature-toggle:3099",
    "CORS_ORIGINS": "*",
}

for k, v in _GOOD_ENV.items():
    os.environ.setdefault(k, v)

# ---------------------------------------------------------------------------
# 2. Mock SQLAlchemy engine so no real DB driver is required at import time
# ---------------------------------------------------------------------------

import sqlalchemy.ext.asyncio as _sqla_async  # noqa: E402

_mock_engine = MagicMock()
_mock_engine.dispose = MagicMock(return_value=None)
_sqla_async.create_async_engine = MagicMock(return_value=_mock_engine)
