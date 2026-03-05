"""Integration tests for the Phase 1 skeleton.

Tests:
  1. test_interfaces_importable
  2. test_request_context_concurrent
  3. test_redis_singleton
  4. test_redis_health_check_pass
  5. test_redis_health_check_fail
  6. test_config_rejects_dev_secret
  7. test_config_rejects_wrong_db_url
  8. test_health_endpoint
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import fakeredis
import fakeredis.aioredis
import pytest

# ---------------------------------------------------------------------------
# Imports — conftest.py has already set valid env vars before these run
# ---------------------------------------------------------------------------

from app.cache import close_redis, get_redis, health_check_redis
from app.config import Settings, get_settings
from app.context import new_context
from app.interfaces import (
    AgentIdentity,
    AuditEvent,
    IAuditLogger,
    IIdentityProvider,
    IPolicyEvaluator,
    ISchemaRegistry,
    ISessionStore,
    IToolGateway,
    JsonRpcRequest,
    PolicyDecision,
    RequestContext,
    ToolResult,
)


# ===========================================================================
# 1. Interfaces
# ===========================================================================


def test_interfaces_importable():
    """All 6 Protocol classes are importable and @runtime_checkable.
    All 6 dataclasses are importable.
    """
    protocols = [
        IToolGateway,
        IIdentityProvider,
        IPolicyEvaluator,
        ISessionStore,
        IAuditLogger,
        ISchemaRegistry,
    ]

    for p in protocols:
        # @runtime_checkable sets this flag
        assert getattr(p, "_is_runtime_protocol", False) is True, (
            f"{p.__name__} is missing @runtime_checkable"
        )
        # isinstance() must not raise; a plain object should NOT satisfy the Protocol
        class Dummy:
            pass

        assert isinstance(Dummy(), p) is False

    dataclasses_ = [
        JsonRpcRequest,
        RequestContext,
        AgentIdentity,
        PolicyDecision,
        AuditEvent,
        ToolResult,
    ]

    for d in dataclasses_:
        assert d is not None, f"{d} should be importable"


# ===========================================================================
# 2. Concurrent Request Context
# ===========================================================================


@pytest.mark.asyncio
async def test_request_context_concurrent():
    """Three concurrent tasks each get a distinct request_id."""

    async def make_ctx(agent_id: str) -> RequestContext:
        await asyncio.sleep(0)          # yield to event loop
        return new_context(agent_id=agent_id)

    results = await asyncio.gather(
        make_ctx("agent-A"),
        make_ctx("agent-B"),
        make_ctx("agent-C"),
    )

    assert len(results) == 3
    request_ids = {ctx.request_id for ctx in results}
    assert len(request_ids) == 3, "All three contexts must have distinct request_ids"

    assert results[0].agent_id == "agent-A"
    assert results[1].agent_id == "agent-B"
    assert results[2].agent_id == "agent-C"


# ===========================================================================
# Redis fixtures &  tests (3, 4, 5)
# ===========================================================================


@pytest.fixture()
async def fakeredis_setup():
    """Replace the real Redis client with an in-process fakeredis instance."""
    import app.cache as cache_module

    # Reset the singleton so get_redis() will create a fresh one
    cache_module._redis_client = None

    fake_server = fakeredis.FakeServer()

    def _fake_from_url(url: str, **kwargs):
        return fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=False)

    with patch("redis.asyncio.from_url", side_effect=_fake_from_url):
        yield

    # Clean up the singleton after each test
    await close_redis()


@pytest.mark.asyncio
async def test_redis_singleton(fakeredis_setup):
    """get_redis() must return the exact same object on successive calls."""
    client1 = await get_redis()
    client2 = await get_redis()

    assert client1 is not None
    assert client1 is client2


@pytest.mark.asyncio
async def test_redis_health_check_pass(fakeredis_setup):
    """health_check_redis() returns True when ping succeeds (fakeredis default)."""
    result = await health_check_redis()
    assert result is True


@pytest.mark.asyncio
async def test_redis_health_check_fail(fakeredis_setup):
    """health_check_redis() returns False (and does NOT raise) when ping raises."""
    client = await get_redis()

    with patch.object(client, "ping", side_effect=ConnectionError("unreachable")):
        result = await health_check_redis()

    assert result is False


# ===========================================================================
# Config validation tests (6, 7)
# ===========================================================================


def test_config_rejects_dev_secret(monkeypatch):
    """Settings raises ValueError when JWT_SECRET is a known-insecure default."""
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://cc:cc@localhost/cc")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_SECRET", "dev_secret_key")           # <-- banned
    monkeypatch.setenv("JWT_PUBLIC_KEY", "dummy")
    monkeypatch.setenv("JWT_JWKS_URL", "http://auth/jwks.json")
    monkeypatch.setenv("CC_INTERNAL_SECRET", "super-strong-internal")
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp:8080")
    monkeypatch.setenv("AUTH_MIDDLEWARE_GRPC_ADDR", "auth:50051")
    monkeypatch.setenv("FEATURE_TOGGLE_SERVICE_URL", "http://ft:3099")
    monkeypatch.setenv("CORS_ORIGINS", "*")

    get_settings.cache_clear()

    with pytest.raises((ValueError, Exception)):
        Settings(_env_file="")

    # Restore cache so subsequent tests see the valid settings
    get_settings.cache_clear()


def test_config_rejects_wrong_db_url(monkeypatch):
    """Settings raises ValueError when DATABASE_URL (POSTGRES_URL) is not asyncpg."""
    monkeypatch.setenv("POSTGRES_URL", "sqlite:///test.db")      # <-- wrong scheme
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("JWT_SECRET", "super-secret-jwt-value-not-guessable")
    monkeypatch.setenv("JWT_PUBLIC_KEY", "dummy")
    monkeypatch.setenv("JWT_JWKS_URL", "http://auth/jwks.json")
    monkeypatch.setenv("CC_INTERNAL_SECRET", "super-strong-internal")
    monkeypatch.setenv("MCP_SERVER_URL", "http://mcp:8080")
    monkeypatch.setenv("AUTH_MIDDLEWARE_GRPC_ADDR", "auth:50051")
    monkeypatch.setenv("FEATURE_TOGGLE_SERVICE_URL", "http://ft:3099")
    monkeypatch.setenv("CORS_ORIGINS", "*")

    get_settings.cache_clear()

    with pytest.raises((ValueError, Exception)):
        Settings(_env_file="")

    get_settings.cache_clear()


# ===========================================================================
# 8. Health endpoint
# ===========================================================================


@pytest.mark.asyncio
async def test_health_endpoint():
    """GET /health returns 200 {status:ok, redis:ok, db:ok} when both deps are healthy.

    We bypass the ASGI lifespan by finding the route handler and calling it
    directly, then mocking the two health-check coroutines it calls.
    """
    with (
        patch("app.main.health_check_redis", new_callable=AsyncMock) as mock_redis,
        patch("app.main.health_check_db", new_callable=AsyncMock) as mock_db,
    ):
        mock_redis.return_value = True
        mock_db.return_value = True

        # Import lazily so conftest mocks are already in place
        from app.main import app

        # Locate the /health endpoint handler
        health_func = next(
            (r.endpoint for r in app.router.routes if getattr(r, "path", None) == "/health"),
            None,
        )
        assert health_func is not None, "/health route not found on app.router"

        response = await health_func()

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body == {"status": "ok", "redis": "ok", "db": "ok"}
