"""Redis cache singleton for the Client Connector service."""

from typing import Optional

import redis.asyncio as redis
import structlog

from app.config import get_settings

logger = structlog.get_logger(__name__)

# Module-level singleton instance
_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create the Redis client singleton.
    
    The client is lazily initialized on the first call using application
    settings for the URL. It is backed by a connection pool.
    
    Returns
    -------
    redis.Redis
        The global async Redis client instance.
    """
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        # Pool size and timeout configuration
        _redis_client = redis.from_url(
            settings.redis_url,
            max_connections=50,
            decode_responses=False,  # Return bytes, callers handle encoding
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        logger.debug("redis_client_initialized", url=settings.redis_url)
    return _redis_client


async def health_check_redis() -> bool:
    """Run a PING to verify Redis connectivity.
    
    Returns
    -------
    bool
        True if Redis is reachable, False otherwise.
    """
    try:
        client = await get_redis()
        # PING returns True if successful
        return await client.ping()
    except Exception as e:
        logger.error("redis_health_check_failed", error=str(e), exc_info=True)
        return False


async def close_redis() -> None:
    """Close the Redis client connection pool and release the singleton."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()  # Close the async client gracefully
            logger.debug("redis_client_closed")
        except Exception as e:
            logger.warning("redis_client_close_error", error=str(e))
        finally:
            _redis_client = None
