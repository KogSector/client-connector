"""Base HTTP Client - Common functionality for service clients."""

import asyncio
import time
from typing import Any, Optional, Dict
from abc import ABC, abstractmethod

import httpx
import structlog

logger = structlog.get_logger()


class BaseHttpClient(ABC):
    """Base class for HTTP clients with common functionality."""
    
    def __init__(self, base_url: str, cache_ttl: float = 60.0, timeout: float = 30.0):
        self.base_url = base_url.rstrip('/')
        self._cache: Dict[str, tuple[Any, float]] = {}
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(timeout=self._timeout)
        logger.info(f"HTTP client started for {self.base_url}")
    
    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info(f"HTTP client stopped for {self.base_url}")
    
    def _get_cache_key(self, endpoint: str, params: Optional[Dict] = None) -> str:
        """Generate cache key for request."""
        key = endpoint
        if params:
            key += "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return key
    
    def _is_cache_valid(self, cached_at: float) -> bool:
        """Check if cache entry is still valid."""
        return time.time() - cached_at < self._cache_ttl
    
    async def _get_cached_response(self, cache_key: str) -> Optional[Any]:
        """Get cached response if valid."""
        if cache_key in self._cache:
            response, cached_at = self._cache[cache_key]
            if self._is_cache_valid(cached_at):
                return response
            else:
                # Remove expired cache entry
                del self._cache[cache_key]
        return None
    
    def _cache_response(self, cache_key: str, response: Any) -> None:
        """Cache response with timestamp."""
        self._cache[cache_key] = (response, time.time())
    
    async def get(self, endpoint: str, params: Optional[Dict] = None, use_cache: bool = True) -> Dict[str, Any]:
        """Make GET request with optional caching."""
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        cache_key = self._get_cache_key(endpoint, params) if use_cache else None
        
        # Check cache first
        if cache_key and use_cache:
            cached_response = await self._get_cached_response(cache_key)
            if cached_response is not None:
                return cached_response
        
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            result = response.json()
            
            # Cache successful response
            if cache_key and use_cache:
                self._cache_response(cache_key, result)
            
            return result
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP GET request failed: {url}", error=str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error in GET request: {url}", error=str(e))
            raise
    
    async def post(self, endpoint: str, data: Optional[Dict] = None, json: Optional[Dict] = None) -> Dict[str, Any]:
        """Make POST request."""
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = await self._client.post(url, data=data, json=json)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP POST request failed: {url}", error=str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error in POST request: {url}", error=str(e))
            raise
    
    async def put(self, endpoint: str, data: Optional[Dict] = None, json: Optional[Dict] = None) -> Dict[str, Any]:
        """Make PUT request."""
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = await self._client.put(url, data=data, json=json)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP PUT request failed: {url}", error=str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error in PUT request: {url}", error=str(e))
            raise
    
    async def delete(self, endpoint: str) -> Dict[str, Any]:
        """Make DELETE request."""
        if not self._client:
            raise RuntimeError("Client not started. Call start() first.")
        
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = await self._client.delete(url)
            response.raise_for_status()
            return response.json() if response.content else {}
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP DELETE request failed: {url}", error=str(e))
            raise
        except Exception as e:
            logger.error(f"Unexpected error in DELETE request: {url}", error=str(e))
            raise
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the service is healthy."""
        pass


class ServiceHealthMixin:
    """Mixin for health check functionality."""
    
    async def check_service_health(self, service_name: str) -> Dict[str, Any]:
        """Check health of a specific service."""
        try:
            if hasattr(self, 'health_check'):
                is_healthy = await self.health_check()
                return {
                    "service": service_name,
                    "status": "healthy" if is_healthy else "unhealthy",
                    "timestamp": time.time()
                }
            else:
                return {
                    "service": service_name,
                    "status": "unknown",
                    "message": "Health check not implemented",
                    "timestamp": time.time()
                }
        except Exception as e:
            return {
                "service": service_name,
                "status": "error",
                "error": str(e),
                "timestamp": time.time()
            }
