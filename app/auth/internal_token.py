"""Internal service-to-service JWT token generation.

Generates short-lived (60 s) tokens that client-connector attaches as
``Authorization: Bearer <token>`` on every outbound call to downstream
internal services (data-vent, embeddings-service, etc.).

Token claims
------------
iss  = "client-connector"   – issuer: this service
sub  = "cc-service"         – subject: machine identity
aud  = "data-connector"     – intended audience
iat  = now (UTC epoch)
exp  = iat + 60 seconds
"""

from __future__ import annotations

import time
from typing import Literal

from jose import jwt

# Fixed claim values — change with caution; receiving services validate these.
_ISSUER = "client-connector"
_SUBJECT = "cc-service"
_AUDIENCE = "data-connector"
_TTL_SECONDS = 60
_ALGORITHM: Literal["HS256"] = "HS256"


def generate_internal_token(secret: str) -> str:
    """Return a signed JWT for service-to-service authentication.

    Parameters
    ----------
    secret:
        The value of ``CC_INTERNAL_SECRET``. Must be a strong, randomly-
        generated string. Callers should obtain this from ``settings``
        rather than constructing it themselves.

    Returns
    -------
    str
        A compact JWT string, ready to use as ``Authorization: Bearer <token>``.

    Raises
    ------
    ValueError
        If *secret* is empty.
    """
    if not secret:
        raise ValueError(
            "CC_INTERNAL_SECRET is empty — cannot generate an internal token."
        )

    now = int(time.time())
    payload: dict = {
        "iss": _ISSUER,
        "sub": _SUBJECT,
        "aud": _AUDIENCE,
        "iat": now,
        "exp": now + _TTL_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm=_ALGORITHM)


def auth_header(secret: str) -> dict[str, str]:
    """Return a ready-to-use ``Authorization`` header dict.

    Convenience wrapper around :func:`generate_internal_token` for use
    inside ``httpx`` call sites::

        response = await client.post(url, json=payload, headers=auth_header(secret))
    """
    return {"Authorization": f"Bearer {generate_internal_token(secret)}"}
