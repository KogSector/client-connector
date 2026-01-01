"""WebSocket transport for MCP protocol."""

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, Query, WebSocket, WebSocketDisconnect, status

from app.config import get_settings
from auth import AuthUser, validate_api_key, validate_jwt_token
from gateway import get_mcp_client
from models import (
    ClientInfo,
    ConnectionState,
    JsonRpcError,
    JsonRpcRequest,
    JsonRpcResponse,
)
from session import ClientSession, get_session_manager

logger = structlog.get_logger()
router = APIRouter()


class WebSocketConnection:
    """Manages a single WebSocket MCP connection."""

    def __init__(
        self,
        websocket: WebSocket,
        session: ClientSession,
        user: AuthUser | None = None,
    ):
        self.websocket = websocket
        self.session = session
        self.user = user
        self._closed = False

    async def send_response(self, response: JsonRpcResponse) -> None:
        """Send a JSON-RPC response."""
        if not self._closed:
            try:
                await self.websocket.send_text(response.model_dump_json())
            except Exception as e:
                logger.error("Failed to send response", error=str(e))
                self._closed = True

    async def send_error(
        self,
        request_id: int | str | None,
        code: int,
        message: str,
        data: Any = None,
    ) -> None:
        """Send an error response."""
        response = JsonRpcResponse(
            id=request_id,
            error=JsonRpcError(code=code, message=message, data=data),
        )
        await self.send_response(response)

    async def handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = json.loads(message)
            request = JsonRpcRequest.model_validate(data)
            
            # Update session activity
            self.session.touch()
            
            # Route to MCP server
            mcp_client = await get_mcp_client()
            response = await mcp_client.send_request(request)
            
            # Update session state on initialize
            if request.method == "initialize" and response.result:
                session_manager = await get_session_manager()
                client_info = None
                if request.params and "clientInfo" in request.params:
                    client_info = ClientInfo.model_validate(request.params["clientInfo"])
                await session_manager.update_session(
                    self.session.id,
                    state=ConnectionState.READY,
                    client_info=client_info,
                )
                logger.info(
                    "Client initialized",
                    session_id=str(self.session.id),
                    client=client_info.name if client_info else "unknown",
                )

            await self.send_response(response)

        except json.JSONDecodeError:
            await self.send_error(None, -32700, "Parse error: Invalid JSON")
        except Exception as e:
            logger.error("Error handling message", error=str(e))
            await self.send_error(None, -32603, f"Internal error: {str(e)}")

    async def close(self) -> None:
        """Close the connection."""
        self._closed = True
        session_manager = await get_session_manager()
        await session_manager.update_session(self.session.id, state=ConnectionState.CLOSED)
        await session_manager.remove_session(self.session.id)


async def authenticate_websocket(
    token: str | None = None,
    api_key: str | None = None,
) -> AuthUser | None:
    """Authenticate WebSocket connection."""
    settings = get_settings()
    
    if token:
        return await validate_jwt_token(token, settings)
    
    if api_key:
        return await validate_api_key(api_key, settings)
    
    return None


@router.websocket("/ws")
async def websocket_mcp_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="JWT token"),
    api_key: str | None = Query(default=None, alias="key", description="API key"),
):
    """WebSocket endpoint for MCP protocol.
    
    Connect with:
    - ws://host:port/mcp/ws?token=<jwt>
    - ws://host:port/mcp/ws?key=<api_key>
    
    For local development, authentication can be optional.
    """
    settings = get_settings()
    
    # Authenticate
    user = await authenticate_websocket(token, api_key)
    
    # In production, require auth; in debug mode, allow anonymous
    if not settings.debug and not user:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Accept connection
    await websocket.accept()
    
    # Create session
    session_manager = await get_session_manager()
    try:
        session = await session_manager.create_session(
            user_id=user.user_id if user else None,
            api_key_id=user.api_key_id if user else None,
        )
    except RuntimeError as e:
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER, reason=str(e))
        return

    # Update session state
    await session_manager.update_session(session.id, state=ConnectionState.INITIALIZING)

    # Create connection handler
    connection = WebSocketConnection(websocket, session, user)

    logger.info(
        "WebSocket connected",
        session_id=str(session.id),
        user_id=user.user_id if user else None,
    )

    try:
        while True:
            message = await websocket.receive_text()
            await connection.handle_message(message)
            
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", session_id=str(session.id))
    except Exception as e:
        logger.error("WebSocket error", session_id=str(session.id), error=str(e))
    finally:
        await connection.close()
