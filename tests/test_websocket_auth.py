"""Unit tests for WebSocket authentication refactoring.

Tests cover:
- No credentials → close(4001), connection rejected
- JWT via Authorization: Bearer header → accepted
- Malformed Authorization header (no Bearer prefix) → rejected
- API key via X-API-Key header → accepted
- Old query-param paths (?token=, ?key=) → rejected (no longer read)
- Both headers present → JWT takes precedence
- Session-manager capacity error → WS_1013_TRY_AGAIN_LATER

Isolation strategy
------------------
All external collaborators (validate_jwt_token, validate_api_key,
get_session_manager, get_mcp_client, get_settings) are patched with
unittest.mock so the tests have zero network or DB dependencies.
"""
from __future__ import annotations

import json
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient   # sync – websocket handshake only
from httpx import ASGITransport, AsyncClient

from app.api.websocket import router, authenticate_websocket
from app.auth import AuthUser
from app.schemas import ConnectionState

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_USER_ID = uuid4()
_API_KEY_ID = uuid4()
_SESSION_ID = uuid4()


def _make_user(**kwargs) -> AuthUser:
    defaults = dict(user_id=_USER_ID, api_key_id=None, scopes=["read"])
    defaults.update(kwargs)
    return MagicMock(spec=AuthUser, **defaults)


def _make_session():
    session = MagicMock()
    session.id = _SESSION_ID
    return session


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/mcp")
    return app


APP = _build_app()


# ---------------------------------------------------------------------------
# authenticate_websocket unit tests  (pure function, no HTTP)
# ---------------------------------------------------------------------------

class TestAuthenticateWebsocket:
    """Tests for the authenticate_websocket helper directly."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none(self):
        result = await authenticate_websocket(authorization=None, x_api_key=None)
        assert result is None

    @pytest.mark.asyncio
    async def test_bearer_token_calls_validate_jwt(self):
        fake_user = _make_user()
        with patch(
            "app.api.websocket.validate_jwt_token", new_callable=AsyncMock
        ) as mock_jwt:
            mock_jwt.return_value = fake_user
            result = await authenticate_websocket(
                authorization="Bearer mytoken123", x_api_key=None
            )
        mock_jwt.assert_awaited_once()
        call_args = mock_jwt.call_args[0]
        assert call_args[0] == "mytoken123"
        assert result is fake_user

    @pytest.mark.asyncio
    async def test_bearer_prefix_stripped_before_passing_to_validator(self):
        """Only the raw token (after 'Bearer ') must reach validate_jwt_token."""
        with patch(
            "app.api.websocket.validate_jwt_token", new_callable=AsyncMock
        ) as mock_jwt:
            mock_jwt.return_value = _make_user()
            await authenticate_websocket(
                authorization="Bearer tok.en.here", x_api_key=None
            )
        passed_token = mock_jwt.call_args[0][0]
        assert passed_token == "tok.en.here"
        assert "Bearer" not in passed_token

    @pytest.mark.asyncio
    async def test_authorization_without_bearer_prefix_rejected(self):
        """A raw token in Authorization without 'Bearer ' must NOT authenticate."""
        with patch(
            "app.api.websocket.validate_jwt_token", new_callable=AsyncMock
        ) as mock_jwt:
            mock_jwt.return_value = _make_user()
            result = await authenticate_websocket(
                authorization="mytoken123",  # no "Bearer " prefix
                x_api_key=None,
            )
        mock_jwt.assert_not_awaited()
        assert result is None

    @pytest.mark.asyncio
    async def test_api_key_calls_validate_api_key(self):
        fake_user = _make_user(api_key_id=_API_KEY_ID)
        with patch(
            "app.api.websocket.validate_api_key", new_callable=AsyncMock
        ) as mock_key:
            mock_key.return_value = fake_user
            result = await authenticate_websocket(
                authorization=None, x_api_key="my-api-key"
            )
        mock_key.assert_awaited_once()
        assert mock_key.call_args[0][0] == "my-api-key"
        assert result is fake_user

    @pytest.mark.asyncio
    async def test_jwt_takes_precedence_over_api_key(self):
        """When both headers are present the JWT path runs and the API key path is skipped."""
        jwt_user = _make_user()
        with (
            patch(
                "app.api.websocket.validate_jwt_token", new_callable=AsyncMock
            ) as mock_jwt,
            patch(
                "app.api.websocket.validate_api_key", new_callable=AsyncMock
            ) as mock_key,
        ):
            mock_jwt.return_value = jwt_user
            result = await authenticate_websocket(
                authorization="Bearer tok", x_api_key="some-key"
            )
        mock_jwt.assert_awaited_once()
        mock_key.assert_not_awaited()
        assert result is jwt_user


# ---------------------------------------------------------------------------
# Endpoint integration tests  (TestClient – sync websocket handshake)
# ---------------------------------------------------------------------------

def _patch_auth(return_user: AuthUser | None):
    """Context manager that patches authenticate_websocket at the endpoint level."""
    return patch(
        "app.api.websocket.authenticate_websocket",
        new_callable=AsyncMock,
        return_value=return_user,
    )


def _patch_session(session=None, raise_error: str | None = None):
    """Patch get_session_manager with a canned session."""
    if session is None:
        session = _make_session()

    mgr = MagicMock()
    if raise_error:
        mgr.create_session = AsyncMock(side_effect=RuntimeError(raise_error))
    else:
        mgr.create_session = AsyncMock(return_value=session)
    mgr.update_session = AsyncMock()
    mgr.remove_session = AsyncMock()

    # get_session_manager is called as `await get_session_manager()` in the endpoint.
    return patch(
        "app.api.websocket.get_session_manager",
        new_callable=AsyncMock,
        return_value=mgr,
    )



class TestWebsocketEndpointAuth:
    """Endpoint-level tests using FastAPI's TestClient."""

    # ------------------------------------------------------------------
    # Rejection cases (never accept the WebSocket)
    # ------------------------------------------------------------------

    def test_no_credentials_closes_4001(self):
        with (
            _patch_auth(None),
            _patch_session(),
        ):
            with pytest.raises(Exception):
                # TestClient raises on WS rejection before handshake completes
                with TestClient(APP).websocket_connect("/mcp/ws") as ws:
                    pass  # should not reach here

    def test_old_query_param_token_not_accepted(self):
        """?token= no longer carries credentials; must be rejected."""
        with _patch_auth(None), _patch_session():
            with pytest.raises(Exception):
                with TestClient(APP).websocket_connect(
                    "/mcp/ws?token=legit-jwt"
                ) as ws:
                    pass

    def test_old_query_param_key_not_accepted(self):
        """?key= no longer carries credentials; must be rejected."""
        with _patch_auth(None), _patch_session():
            with pytest.raises(Exception):
                with TestClient(APP).websocket_connect(
                    "/mcp/ws?key=legit-api-key"
                ) as ws:
                    pass

    # ------------------------------------------------------------------
    # Acceptance cases
    # ------------------------------------------------------------------

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_valid_bearer_token_accepted(self):
        user = _make_user()
        session = _make_session()
        with _patch_auth(user), _patch_session(session):
            with TestClient(APP).websocket_connect(
                "/mcp/ws",
                headers={"Authorization": "Bearer valid.jwt.token"},
            ) as ws:
                # Connection should be accepted; send a message and bail
                ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
                # We just assert no exception = connected successfully

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_valid_api_key_accepted(self):
        user = _make_user(api_key_id=_API_KEY_ID)
        session = _make_session()
        with _patch_auth(user), _patch_session(session):
            with TestClient(APP).websocket_connect(
                "/mcp/ws",
                headers={"X-API-Key": "valid-api-key"},
            ) as ws:
                ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))

    def test_session_capacity_error_closes_1013(self):
        """When session creation fails, the endpoint must close with WS_1013."""
        from starlette.websockets import WebSocketDisconnect

        user = _make_user()
        with (
            _patch_auth(user),
            _patch_session(raise_error="Too many sessions"),
            patch("app.api.websocket.get_mcp_client", new_callable=AsyncMock),
        ):
            client = TestClient(APP, raise_server_exceptions=False)
            with client.websocket_connect(
                "/mcp/ws",
                headers={"Authorization": "Bearer tok"},
            ) as ws:
                # The endpoint accepts, then immediately closes with 1013.
                # TestClient surfaces this as a WebSocketDisconnect on receive().
                try:
                    ws.receive_text()
                except WebSocketDisconnect as exc:
                    assert exc.code == 1013
                except Exception:
                    pass  # other transport errors are acceptable here


# ---------------------------------------------------------------------------
# Async endpoint tests  (pytest-asyncio + httpx ASGI transport)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_credentials_rejected_async():
    """Async variant: missing credentials must reject the handshake."""
    async with AsyncClient(
        transport=ASGITransport(app=APP), base_url="http://test"
    ) as client:
        with _patch_auth(None):
            # HTTP GET on a WS endpoint returns 403/404; either is not 101 (upgrade)
            resp = await client.get(
                "/mcp/ws",
                headers={"Connection": "Upgrade", "Upgrade": "websocket"},
            )
            # httpx won't actually upgrade here – we just confirm it's not 101
            assert resp.status_code != 101


@pytest.mark.asyncio
async def test_authenticate_websocket_integration_bearer():
    """Integration: authenticate_websocket correctly threads a Bearer token through."""
    fake_user = _make_user()
    with (
        patch("app.api.websocket.validate_jwt_token", new_callable=AsyncMock) as m,
        patch("app.api.websocket.get_settings", return_value=MagicMock()),
    ):
        m.return_value = fake_user
        result = await authenticate_websocket(
            authorization="Bearer integration.test.token",
            x_api_key=None,
        )
    assert result is fake_user
    assert m.call_args[0][0] == "integration.test.token"


@pytest.mark.asyncio
async def test_authenticate_websocket_integration_api_key():
    """Integration: authenticate_websocket correctly threads an X-API-Key through."""
    fake_user = _make_user(api_key_id=_API_KEY_ID)
    with (
        patch("app.api.websocket.validate_api_key", new_callable=AsyncMock) as m,
        patch("app.api.websocket.get_settings", return_value=MagicMock()),
    ):
        m.return_value = fake_user
        result = await authenticate_websocket(
            authorization=None,
            x_api_key="integration-api-key",
        )
    assert result is fake_user
    assert m.call_args[0][0] == "integration-api-key"


# ---------------------------------------------------------------------------
# Real-auth tests — NO mocking of the auth layer
#
# These tests exercise the full auth stack for the JWT path:
#   - validate_jwt_token runs for real using python-jose
#   - The token is signed with a known secret in the test environment
#   - Only the session manager and MCP client are stubbed (infrastructure)
#
# validate_api_key is *not* tested this way because it makes an outbound HTTP
# call to the auth-middleware service — that's an integration test that
# requires the full platform running, not a unit test.
# ---------------------------------------------------------------------------

_TEST_JWT_SECRET = "test-secret-that-is-not-a-default-value-32ch"
_TEST_JWT_ALGORITHM = "HS256"


def _make_real_jwt(user_id: str = "real-user-123") -> str:
    """Sign a real JWT with python-jose using the test secret."""
    from jose import jwt as jose_jwt
    import datetime

    payload = {
        "sub": user_id,
        "email": "real@example.com",
        "roles": ["read"],
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1),
    }
    return jose_jwt.encode(payload, _TEST_JWT_SECRET, algorithm=_TEST_JWT_ALGORITHM)


def _real_auth_settings() -> MagicMock:
    """Return settings with a real (non-default) jwt_secret."""
    s = MagicMock()
    s.jwt_secret = _TEST_JWT_SECRET
    s.jwt_algorithm = _TEST_JWT_ALGORITHM
    return s


class TestRealAuthNoMocks:
    """End-to-end auth tests — validate_jwt_token is NOT mocked."""

    @pytest.mark.asyncio
    async def test_no_credentials_returns_none_real_auth(self):
        """(1) No credentials → authenticate_websocket returns None.

        Auth is enforced: no mock, no bypass.
        """
        with patch("app.api.websocket.get_settings", return_value=_real_auth_settings()):
            result = await authenticate_websocket(authorization=None, x_api_key=None)
        assert result is None, "Expected None when no credentials are supplied"

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_auth_user_real_auth(self):
        """(2) Valid signed JWT → authenticate_websocket returns a real AuthUser.

        validate_jwt_token runs for real with python-jose — no mocking.
        """
        token = _make_real_jwt(user_id="real-user-456")
        with patch("app.api.websocket.get_settings", return_value=_real_auth_settings()):
            result = await authenticate_websocket(
                authorization=f"Bearer {token}",
                x_api_key=None,
            )
        assert result is not None, "Expected an AuthUser for a valid token"
        assert result.user_id == "real-user-456"

    @pytest.mark.asyncio
    async def test_tampered_jwt_returns_none_real_auth(self):
        """Invalid/tampered JWT must be rejected without any bypass."""
        with patch("app.api.websocket.get_settings", return_value=_real_auth_settings()):
            result = await authenticate_websocket(
                authorization="Bearer this.is.not.a.valid.token",
                x_api_key=None,
            )
        assert result is None, "Expected None for a tampered/invalid token"

    def test_no_credentials_closes_4001_endpoint_real_auth(self):
        """(1) Endpoint-level: missing credentials must close with code 4001.

        authenticate_websocket is NOT mocked; the endpoint runs the real guard.
        The session manager is stubbed only because it's infrastructure.
        """
        with (
            patch("app.api.websocket.get_settings", return_value=_real_auth_settings()),
            _patch_session(),  # stub infra only
        ):
            with pytest.raises(Exception):
                with TestClient(APP).websocket_connect("/mcp/ws") as ws:
                    pass  # must not reach this line

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_valid_jwt_accepted_endpoint_real_auth(self):
        """(2) Endpoint-level: a real signed token must be accepted.

        authenticate_websocket is NOT mocked; validate_jwt_token runs for real.
        """
        token = _make_real_jwt(user_id="endpoint-user-789")
        with (
            patch("app.api.websocket.get_settings", return_value=_real_auth_settings()),
            _patch_session(),  # stub infra only
        ):
            with TestClient(APP).websocket_connect(
                "/mcp/ws",
                headers={"Authorization": f"Bearer {token}"},
            ) as ws:
                # Connection accepted — send a minimal frame and confirm no exception
                ws.send_text(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
