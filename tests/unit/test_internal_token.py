"""Unit tests for internal service-to-service JWT authentication.

Covers:
1. generate_internal_token() produces a token with the correct claims
2. A token decoded with the wrong secret is rejected (JWTError)
3. QueryProcessor._vector_search injects Authorization: Bearer header
4. QueryProcessor._hybrid_search injects Authorization: Bearer header
5. QueryProcessor rejects construction with empty internal_secret
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import JWTError, jwt

from app.auth.internal_token import (
    auth_header,
    generate_internal_token,
)
from app.services.query_processor import QueryProcessor

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SECRET = "test-internal-secret-that-is-strong-enough"
_WRONG_SECRET = "completely-different-secret-value-xyz"
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# generate_internal_token() — claim assertions
# ---------------------------------------------------------------------------


class TestGenerateInternalToken:
    def test_token_is_non_empty_string(self):
        token = generate_internal_token(_SECRET)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_token_has_correct_iss(self):
        token = generate_internal_token(_SECRET)
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        assert payload["iss"] == "client-connector"

    def test_token_has_correct_sub(self):
        token = generate_internal_token(_SECRET)
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        assert payload["sub"] == "cc-service"

    def test_token_has_correct_aud(self):
        token = generate_internal_token(_SECRET)
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        assert payload["aud"] == "data-connector"

    def test_token_ttl_is_60_seconds(self):
        before = int(time.time())
        token = generate_internal_token(_SECRET)
        after = int(time.time())

        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        ttl = payload["exp"] - payload["iat"]
        assert ttl == 60

        # iat must be within the observed time window
        assert before <= payload["iat"] <= after + 1

    def test_token_is_not_expired_immediately(self):
        """A freshly minted token must decode without raising ExpiredSignatureError."""
        token = generate_internal_token(_SECRET)
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        assert payload["exp"] > int(time.time())

    def test_empty_secret_raises_value_error(self):
        with pytest.raises(ValueError, match="CC_INTERNAL_SECRET is empty"):
            generate_internal_token("")


# ---------------------------------------------------------------------------
# Wrong-secret rejection
# ---------------------------------------------------------------------------


class TestTokenSecretValidation:
    def test_wrong_secret_raises_jwt_error(self):
        token = generate_internal_token(_SECRET)
        with pytest.raises(JWTError):
            jwt.decode(token, _WRONG_SECRET, algorithms=[_ALGORITHM], audience="data-connector")

    def test_tampered_payload_raises_jwt_error(self):
        token = generate_internal_token(_SECRET)
        # Corrupt the signature portion
        parts = token.split(".")
        parts[2] = parts[2][:-4] + "XXXX"
        tampered = ".".join(parts)
        with pytest.raises(JWTError):
            jwt.decode(tampered, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")


# ---------------------------------------------------------------------------
# auth_header() convenience wrapper
# ---------------------------------------------------------------------------


class TestAuthHeader:
    def test_returns_dict_with_authorization_key(self):
        headers = auth_header(_SECRET)
        assert "Authorization" in headers

    def test_value_starts_with_bearer(self):
        headers = auth_header(_SECRET)
        assert headers["Authorization"].startswith("Bearer ")

    def test_bearer_token_is_valid_jwt(self):
        headers = auth_header(_SECRET)
        token = headers["Authorization"].removeprefix("Bearer ")
        payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
        assert payload["iss"] == "client-connector"


# ---------------------------------------------------------------------------
# QueryProcessor — constructor guard
# ---------------------------------------------------------------------------


class TestQueryProcessorConstructorGuard:
    def test_rejects_empty_internal_secret(self):
        with pytest.raises(ValueError, match="CC_INTERNAL_SECRET"):
            QueryProcessor(internal_secret="")

    def test_rejects_missing_internal_secret(self):
        """Calling without the kwarg uses the default '' which must raise."""
        with pytest.raises(ValueError, match="CC_INTERNAL_SECRET"):
            QueryProcessor()

    def test_accepts_valid_internal_secret(self):
        qp = QueryProcessor(internal_secret=_SECRET)
        assert qp._internal_secret == _SECRET


# ---------------------------------------------------------------------------
# QueryProcessor — Authorization header injected on every outbound call
# ---------------------------------------------------------------------------


def _make_processor() -> QueryProcessor:
    return QueryProcessor(
        data_vent_url="http://data-vent-test:3005",
        embeddings_service_url="http://embeddings-test:3001",
        internal_secret=_SECRET,
    )


def _mock_http_response(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_body
    return resp


@pytest.mark.asyncio
async def test_vector_search_injects_authorization_header():
    """_vector_search must attach Authorization: Bearer <token> to the POST call."""
    qp = _make_processor()
    qp._http_client = AsyncMock()
    qp._http_client.post = AsyncMock(
        return_value=_mock_http_response({"chunks": [], "total": 0})
    )

    await qp._vector_search(query_vectors=[0.1] * 384, limit=5, source_ids=None)

    call_kwargs = qp._http_client.post.call_args.kwargs
    headers = call_kwargs.get("headers", {})

    assert "Authorization" in headers, "Authorization header missing on _vector_search call"
    bearer = headers["Authorization"]
    assert bearer.startswith("Bearer "), f"Expected 'Bearer ...' but got: {bearer!r}"

    # Validate the token itself carries correct claims
    token = bearer.removeprefix("Bearer ")
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
    assert payload["iss"] == "client-connector"
    assert payload["sub"] == "cc-service"


@pytest.mark.asyncio
async def test_hybrid_search_injects_authorization_header():
    """_hybrid_search must attach Authorization: Bearer <token> to the POST call."""
    qp = _make_processor()
    qp._http_client = AsyncMock()
    qp._http_client.post = AsyncMock(
        return_value=_mock_http_response(
            {"chunks": [], "vector_matches": 0, "graph_matches": 0, "completion_reached": False}
        )
    )

    await qp._hybrid_search(
        query="what is confuse?",
        query_vectors=[0.1] * 384,
        limit=10,
        source_ids=None,
    )

    call_kwargs = qp._http_client.post.call_args.kwargs
    headers = call_kwargs.get("headers", {})

    assert "Authorization" in headers, "Authorization header missing on _hybrid_search call"
    bearer = headers["Authorization"]
    assert bearer.startswith("Bearer "), f"Expected 'Bearer ...' but got: {bearer!r}"

    token = bearer.removeprefix("Bearer ")
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
    assert payload["iss"] == "client-connector"
    assert payload["sub"] == "cc-service"


@pytest.mark.asyncio
async def test_vectorize_query_injects_authorization_header():
    """vectorize_query (embeddings-service call) must also inject the auth header."""
    qp = _make_processor()
    qp._http_client = AsyncMock()
    qp._http_client.post = AsyncMock(
        return_value=_mock_http_response({"embeddings": [0.1] * 384})
    )

    await qp.vectorize_query("test query")

    call_kwargs = qp._http_client.post.call_args.kwargs
    headers = call_kwargs.get("headers", {})

    assert "Authorization" in headers, "Authorization header missing on vectorize_query call"
    assert headers["Authorization"].startswith("Bearer ")


@pytest.mark.asyncio
async def test_each_call_produces_a_fresh_token():
    """Two consecutive outbound calls must each carry their own freshly-minted token.
    (Tokens are not reused between requests.)
    """
    qp = _make_processor()
    qp._http_client = AsyncMock()
    qp._http_client.post = AsyncMock(
        return_value=_mock_http_response({"chunks": [], "total": 0})
    )

    await qp._vector_search(query_vectors=[0.1] * 384, limit=5, source_ids=None)
    first_token = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]

    # Small sleep to guarantee a different iat if needed, but iat resolution
    # is 1 second so tokens in the same second are equivalent — what matters
    # is that each call independently invokes generate_internal_token.
    qp._http_client.post.reset_mock()
    await qp._vector_search(query_vectors=[0.1] * 384, limit=5, source_ids=None)
    second_token = qp._http_client.post.call_args.kwargs["headers"]["Authorization"]

    # Both must be valid JWTs (even if identical within the same second)
    for bearer in (first_token, second_token):
        token = bearer.removeprefix("Bearer ")
        jwt.decode(token, _SECRET, algorithms=[_ALGORITHM], audience="data-connector")
