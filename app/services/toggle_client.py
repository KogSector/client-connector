"""Feature Toggle client for client-connector.

Integrates with the feature-toggle service directly via database.
As per platform rules, features default to disabled when database is unavailable.
"""

import asyncio
import time
from typing import Any

import structlog
from sqlalchemy import text

from app.infra.db.postgres import get_session

logger = structlog.get_logger()


class FeatureToggleClient:
    """Client for feature-toggle service with caching from direct DB.

    Supports checking toggle states for:
    - devOnly: Developer shortcuts (always disabled in production)
    - userFacing: User-visible features
    - ops: Operational toggles
    """

    def __init__(self, cache_ttl: float = 30.0):
        self._cache: dict[str, tuple[bool, float]] = {}
        self._cache_ttl = cache_ttl
        self._lock = asyncio.Lock()

    async def is_enabled(self, toggle_name: str, default: bool = False) -> bool:
        """Check if a feature toggle is enabled.

        Args:
            toggle_name: Name of the toggle (e.g., 'mcpWebsocketTransport')
            default: Default value if database is unavailable

        Returns:
            True if toggle is enabled, False otherwise.
            Defaults to False if service unavailable (safe default per platform rules).
        """
        # Check cache first
        now = time.time()
        if toggle_name in self._cache:
            enabled, cached_at = self._cache[toggle_name]
            if now - cached_at < self._cache_ttl:
                return enabled

        # Fetch from database
        try:
            async with get_session() as session:
                result = await session.execute(
                    text("SELECT enabled FROM feature_toggles.toggles WHERE name = :name"),
                    {"name": toggle_name},
                )
                row = result.fetchone()

                if row is not None:
                    enabled = bool(row[0])

                    # Cache the result
                    async with self._lock:
                        self._cache[toggle_name] = (enabled, now)

                    return enabled
                else:
                    logger.debug("Toggle not found in DB", toggle=toggle_name)
                    return default

        except Exception as e:
            logger.warning(
                "Feature toggle check failed (DB error)", toggle=toggle_name, error=str(e)
            )

            # Fallback to stale cache if available
            if toggle_name in self._cache:
                return self._cache[toggle_name][0]

        # Default to disabled when service unavailable (per platform rules)
        return default

    async def get_toggle(self, toggle_name: str) -> dict[str, Any] | None:
        """Get full toggle details including metadata.

        Returns:
            Toggle dict with name, enabled, description, category, metadata
            or None if not found.
        """
        try:
            async with get_session() as session:
                result = await session.execute(
                    text(
                        "SELECT name, enabled, description, category, category_type, metadata FROM feature_toggles.toggles WHERE name = :name"
                    ),
                    {"name": toggle_name},
                )
                row = result.fetchone()
                if row is not None:
                    return {
                        "name": row[0],
                        "enabled": bool(row[1]),
                        "description": row[2],
                        "category": row[3],
                        "category_type": row[4],
                        "metadata": row[5],
                    }
        except Exception as e:
            logger.warning("Failed to get toggle details from DB", toggle=toggle_name, error=str(e))
        return None

    def clear_cache(self) -> None:
        """Clear the toggle cache."""
        self._cache.clear()


# Global singleton
_toggle_client: FeatureToggleClient | None = None


async def get_toggle_client() -> FeatureToggleClient:
    """Get or create feature toggle client singleton."""
    global _toggle_client
    if _toggle_client is None:
        _toggle_client = FeatureToggleClient()
    return _toggle_client


async def is_feature_enabled(toggle_name: str, default: bool = False) -> bool:
    """Convenience function to check if a feature is enabled.

    Usage:
        if await is_feature_enabled('mcpWebsocketTransport'):
            # Enable WebSocket transport
    """
    client = await get_toggle_client()
    return await client.is_enabled(toggle_name, default)
