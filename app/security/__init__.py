"""
ConFuse Common Middleware Module

Authentication, rate limiting, and security headers for FastAPI services.
"""

from .auth import (
    AuthMiddleware,
    AuthenticatedUser,
    get_current_user,
    get_optional_user,
)
from .rate_limit import RateLimitMiddleware
from .security_headers import SecurityHeadersMiddleware

__all__ = [
    "AuthMiddleware",
    "AuthenticatedUser",
    "get_current_user",
    "get_optional_user",
    "RateLimitMiddleware",
    "SecurityHeadersMiddleware",
]
