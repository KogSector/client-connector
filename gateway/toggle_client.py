"""Feature Toggle client for client-connector.

Integrates with the feature-context-toggle service to check toggle states.
As per platform rules, features default to disabled when toggle service is unavailable.
"""

import asyncio
import time
from typing import Any

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()


class FeatureToggleClient:
    """Client for feature-toggle service with caching.
    
    Supports checking toggle states for:
    - devOnly: Developer shortcuts (always disabled in production)
    - userFacing: User-visible features  
    - ops: Operational toggles
    """

    def __init__(self, base_url: str, cache_ttl: float = 60.0):
        self.base_url = base_url
        self._cache: dict[str, tuple[bool, float]] = {}
        self._cache_ttl = cache_ttl
        self._lock = asyncio.Lock()

    async def is_enabled(self, toggle_name: str, default: bool = False) -> bool:
        """Check if a feature toggle is enabled.
        
        Args:
            toggle_name: Name of the toggle (e.g., 'mcpWebsocketTransport')
            default: Default value if toggle service is unavailable
            
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

        # Fetch from service
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/toggles/{toggle_name}",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    data = response.json()
                    enabled = data.get("enabled", default)
                    
                    # Cache the result
                    async with self._lock:
                        self._cache[toggle_name] = (enabled, now)
                    
                    return enabled
                elif response.status_code == 404:
                    logger.debug("Toggle not found", toggle=toggle_name)
                    return default
                    
        except httpx.TimeoutException:
            logger.warning("Feature toggle timeout", toggle=toggle_name)
        except httpx.ConnectError:
            logger.warning("Feature toggle service unavailable", toggle=toggle_name)
        except Exception as e:
            logger.warning("Feature toggle check failed", toggle=toggle_name, error=str(e))

        # Default to disabled when service unavailable (per platform rules)
        return default

    async def get_toggle(self, toggle_name: str) -> dict[str, Any] | None:
        """Get full toggle details including metadata.
        
        Returns:
            Toggle dict with name, enabled, description, category, metadata
            or None if not found.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/api/toggles/{toggle_name}",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    return response.json()
        except Exception as e:
            logger.warning("Failed to get toggle details", toggle=toggle_name, error=str(e))
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
        settings = get_settings()
        _toggle_client = FeatureToggleClient(settings.feature_toggle_url)
    return _toggle_client


async def is_feature_enabled(toggle_name: str, default: bool = False) -> bool:
    """Convenience function to check if a feature is enabled.
    
    Usage:
        if await is_feature_enabled('mcpWebsocketTransport'):
            # Enable WebSocket transport
    """
    client = await get_toggle_client()
    return await client.is_enabled(toggle_name, default)
