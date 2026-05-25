import asyncio
import uuid
import structlog
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse
from mcp.server.sse import SseServerTransport
from app.mcp_server import get_mcp_app

logger = structlog.get_logger()
router = APIRouter(prefix="/mcp", tags=["MCP SSE"])

# Global session management for SSE
_transports = {}

@router.get("/sse")
async def sse_endpoint(request: Request, agent_id: str | None = None):
    """
    Establish an MCP SSE connection.
    """
    mcp_app = get_mcp_app()
    session_id = agent_id or str(uuid.uuid4())
    
    # Use a clean relative path for the messages endpoint.
    # The session_id will be handled via a query parameter by our POST handler.
    transport = SseServerTransport("/mcp/messages")
    _transports[session_id] = transport
    
    logger.info("MCP SSE connection initiated", session_id=session_id)

    async def event_generator():
        try:
            # Note: connect_sse handles the handshake
            async with transport.connect_sse(
                request.scope, request.receive, request._send
            ) as (read_stream, write_stream):
                # Run the MCP server in the background
                server_task = asyncio.create_task(
                    mcp_app._server.run(
                        read_stream,
                        write_stream,
                        mcp_app._server.create_initialization_options()
                    )
                )
                
                # We need to send the session_id to the client so it knows how to POST
                # The MCP SSE spec says the client should get the endpoint in an 'endpoint' event
                # SseServerTransport.sse_events() yields events, including the initial 'endpoint' one
                # but it uses the path we gave it. We need to append the session_id.
                
                async for event in transport.sse_events():
                    if await request.is_disconnected():
                        break
                    
                    # If this is the endpoint event, append our session_id
                    if event.event == "endpoint" and "session_id=" not in event.data:
                        event.data = f"{event.data}?session_id={session_id}"
                    
                    yield event
                
                server_task.cancel()
        except Exception as e:
            logger.error("Error in MCP SSE stream", error=str(e), session_id=session_id)
        finally:
            if session_id in _transports:
                del _transports[session_id]
            logger.info("MCP SSE transport closed", session_id=session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

@router.post("/messages")
async def messages_endpoint(request: Request, session_id: str):
    """
    Receive messages from an MCP SSE client.
    """
    transport = _transports.get(session_id)
    if not transport:
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        await transport.handle_post_message(request.scope, request.receive, request._send)
        return {"status": "ok"}
    except Exception as e:
        logger.error("Error handling MCP message", error=str(e), session_id=session_id)
        raise HTTPException(status_code=500, detail=str(e))
