"""Tests for WebSocket transport."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from models import JsonRpcRequest, JsonRpcResponse, ConnectionState


@pytest.fixture
def mock_settings():
    """Mock settings for tests."""
    with patch("app.config.get_settings") as mock:
        settings = MagicMock()
        settings.debug = True
        settings.mcp_server_mode = "subprocess"
        settings.mcp_server_path = "/path/to/mcp"
        settings.max_concurrent_clients = 100
        settings.session_timeout_minutes = 60
        mock.return_value = settings
        yield settings


@pytest.fixture
def mock_mcp_client():
    """Mock MCP client for tests."""
    with patch("gateway.mcp_client.get_mcp_client") as mock:
        client = AsyncMock()
        client.is_running = True
        client.send_request = AsyncMock(
            return_value=JsonRpcResponse(
                id=1,
                result={"protocolVersion": "2024-11-05"},
            )
        )
        mock.return_value = client
        yield client


class TestJsonRpcRequest:
    """Tests for JsonRpcRequest model."""

    def test_basic_request(self):
        req = JsonRpcRequest(method="initialize")
        assert req.jsonrpc == "2.0"
        assert req.method == "initialize"
        assert req.id is None
        assert req.params is None

    def test_request_with_params(self):
        req = JsonRpcRequest(
            id=1,
            method="tools/call",
            params={"name": "fs.read_file", "arguments": {"path": "/test"}},
        )
        assert req.id == 1
        assert req.params["name"] == "fs.read_file"

    def test_request_serialization(self):
        req = JsonRpcRequest(id=1, method="tools/list")
        json_str = req.model_dump_json()
        assert '"method":"tools/list"' in json_str


class TestJsonRpcResponse:
    """Tests for JsonRpcResponse model."""

    def test_success_response(self):
        resp = JsonRpcResponse(id=1, result={"tools": []})
        assert resp.jsonrpc == "2.0"
        assert resp.error is None
        assert resp.result == {"tools": []}

    def test_error_response(self):
        from models import JsonRpcError
        
        resp = JsonRpcResponse(
            id=1,
            error=JsonRpcError(code=-32600, message="Invalid Request"),
        )
        assert resp.result is None
        assert resp.error.code == -32600


class TestConnectionState:
    """Tests for connection state enum."""

    def test_states(self):
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.READY.value == "ready"
        assert ConnectionState.CLOSED.value == "closed"


# Integration test would require full app context
@pytest.mark.asyncio
async def test_session_creation(mock_settings):
    """Test session manager creates sessions."""
    from session.manager import SessionManager
    
    manager = SessionManager()
    session = await manager.create_session(user_id="test-user")
    
    assert session.id is not None
    assert session.user_id == "test-user"
    assert session.state == ConnectionState.CONNECTING
    
    # Cleanup
    await manager.remove_session(session.id)


@pytest.mark.asyncio
async def test_session_expiry(mock_settings):
    """Test session expiry detection."""
    from session.manager import ClientSession
    from datetime import datetime, timedelta
    
    session = ClientSession(user_id="test")
    session.last_activity = datetime.utcnow() - timedelta(minutes=120)
    
    assert session.is_expired(60) is True
    
    session.touch()
    assert session.is_expired(60) is False
