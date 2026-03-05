"""Unit tests for the Redis cache singleton."""

import pytest
from unittest.mock import patch, MagicMock

import fakeredis.aioredis

from app.cache import get_redis, health_check_redis, close_redis


@pytest.fixture(autouse=True)
async def reset_redis_singleton():
    """Ensure the singleton is reset before and after each test."""
    import app.cache
    app.cache._redis_client = None
    yield
    await close_redis()


@pytest.fixture
def mock_fakeredis():
    """Patch redis.from_url to use fakeredis instead."""
    fake_server = fakeredis.FakeServer()
    
    def fake_from_url(url, **kwargs):
        return fakeredis.aioredis.FakeRedis(server=fake_server, **kwargs)

    with patch("redis.asyncio.from_url", side_effect=fake_from_url) as mock_from_url:
        yield mock_from_url


@pytest.mark.asyncio
async def test_get_redis_singleton(mock_fakeredis):
    """Verify get_redis returns the exact same client on successive calls."""
    client1 = await get_redis()
    client2 = await get_redis()
    
    # Expected to only call from_url once
    mock_fakeredis.assert_called_once()
    
    # Needs to be exactly the same instance
    assert client1 is client2
    assert client1 is not None


@pytest.mark.asyncio
async def test_health_check_pass(mock_fakeredis):
    """Verify health_check_redis returns True when PING succeeds."""
    # fakeredis natively supports handling ping() properly
    is_healthy = await health_check_redis()
    assert is_healthy is True


@pytest.mark.asyncio
async def test_health_check_fail():
    """Verify health_check_redis handles exceptions and returns False."""
    with patch("app.cache.get_redis", side_effect=Exception("Redis timeout")):
        is_healthy = await health_check_redis()
        assert is_healthy is False


@pytest.mark.asyncio
async def test_close_redis_and_reinitialize(mock_fakeredis):
    """Verify close_redis drops the singleton, allowing for re-initialization."""
    # Initialize fake client
    client1 = await get_redis()
    mock_fakeredis.assert_called_once()
    assert client1 is not None

    # Call close
    await close_redis()

    import app.cache
    assert app.cache._redis_client is None

    # Re-initialize should create a new client
    client2 = await get_redis()
    assert mock_fakeredis.call_count == 2
    assert client1 is not client2
