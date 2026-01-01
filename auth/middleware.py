"""Authentication middleware and utilities."""

import time
from typing import Annotated, Any
from uuid import UUID

import httpx
import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from jose import JWTError, jwt

from app.config import Settings, get_settings

logger = structlog.get_logger()


class AuthUser:
    """Authenticated user from JWT or API key."""

    def __init__(
        self,
        user_id: str,
        email: str | None = None,
        roles: list[str] | None = None,
        api_key_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        self.user_id = user_id
        self.email = email
        self.roles = roles or []
        self.api_key_id = api_key_id
        self.metadata = metadata or {}

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def __repr__(self) -> str:
        return f"AuthUser(user_id={self.user_id}, email={self.email})"


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, limit_per_minute: int, burst: int):
        self.limit_per_minute = limit_per_minute
        self.burst = burst
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed for the given key."""
        now = time.time()
        window_start = now - 60  # 1 minute window

        # Clean old requests
        if key in self._requests:
            self._requests[key] = [t for t in self._requests[key] if t > window_start]
        else:
            self._requests[key] = []

        # Check rate
        if len(self._requests[key]) >= self.limit_per_minute:
            return False

        # Record request
        self._requests[key].append(now)
        return True

    def get_remaining(self, key: str) -> int:
        """Get remaining requests for the key."""
        now = time.time()
        window_start = now - 60
        
        if key not in self._requests:
            return self.limit_per_minute
            
        recent = [t for t in self._requests[key] if t > window_start]
        return max(0, self.limit_per_minute - len(recent))


# Global rate limiter
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Get rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        settings = get_settings()
        _rate_limiter = RateLimiter(
            limit_per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        )
    return _rate_limiter


async def validate_jwt_token(
    token: str,
    settings: Settings,
) -> AuthUser | None:
    """Validate JWT token and return user info."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        
        user_id = payload.get("sub")
        if not user_id:
            return None

        return AuthUser(
            user_id=user_id,
            email=payload.get("email"),
            roles=payload.get("roles", []),
            metadata=payload.get("metadata", {}),
        )
    except JWTError as e:
        logger.warning("JWT validation failed", error=str(e))
        return None


async def validate_api_key(
    api_key: str,
    settings: Settings,
) -> AuthUser | None:
    """Validate API key against auth-middleware service."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.auth_middleware_url}/api/auth/validate-key",
                json={"api_key": api_key},
                timeout=10.0,
            )
            
            if response.status_code == 200:
                data = response.json()
                return AuthUser(
                    user_id=data.get("user_id", ""),
                    email=data.get("email"),
                    roles=data.get("roles", []),
                    api_key_id=data.get("key_id"),
                )
    except Exception as e:
        logger.error("API key validation failed", error=str(e))
    
    return None


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> AuthUser:
    """FastAPI dependency for authenticated user."""
    
    # Check rate limit first
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter = get_rate_limiter()
    
    if not rate_limiter.is_allowed(client_ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    # Try JWT token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        user = await validate_jwt_token(token, settings)
        if user:
            return user

    # Try API key
    if x_api_key:
        user = await validate_api_key(x_api_key, settings)
        if user:
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing authentication",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_optional_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> AuthUser | None:
    """FastAPI dependency for optional authenticated user."""
    try:
        return await get_current_user(request, authorization, x_api_key, settings)
    except HTTPException:
        return None
