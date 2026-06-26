"""
MCP Server — ConFuse Knowledge Search

Exposes a single MCP tool (query_knowledge) to AI agents.
Accepts natural-language queries, compresses them via PromptCompressor,
forwards to data-vent for retrieval, and compresses the response
before returning it to the agent.
"""

import os
import uuid
from typing import Any

import httpx
import structlog
from mcp.server.fastmcp import FastMCP

from app.services.prompt_compressor import PromptCompressor

logger = structlog.get_logger()

# Initialize FastMCP server
mcp = FastMCP("ConFuse Knowledge Search")

# data-vent retrieval service (configured in .env.map)
DATA_VENT_URL = os.getenv("DATA_VENT_URL", "http://127.0.0.1:3005")
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT_SECS", "30"))

# Shared compressor instance
_compressor = PromptCompressor()

# --- MONKEY PATCH FOR ABSOLUTE ENDPOINT URLs ---
import mcp.server.sse
from urllib.parse import quote
from starlette.requests import Request
import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.types import SessionMessage, ServerMessageMetadata
import mcp.types as types
from uuid import uuid4
import logging
from sse_starlette.sse import EventSourceResponse
from typing import Any

original_connect_sse = mcp.server.sse.SseServerTransport.connect_sse

import contextlib
@contextlib.asynccontextmanager
async def patched_connect_sse(self, scope, receive, send):
    request = Request(scope, receive)
    error_response = await self._security.validate_request(request, is_post=False)
    if error_response:
        await error_response(scope, receive, send)
        raise ValueError("Request validation failed")

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    session_id = uuid4()
    self._read_stream_writers[session_id] = read_stream_writer

    # Construct absolute URL!
    base_url = str(request.base_url).rstrip("/")
    # self._endpoint is e.g. "/messages/"
    full_message_path = base_url + self._endpoint
    client_post_uri_data = f"{full_message_path}?session_id={session_id.hex}"

    sse_stream_writer, sse_stream_reader = anyio.create_memory_object_stream(0)

    async def sse_writer():
        async with sse_stream_writer, write_stream_reader:
            await sse_stream_writer.send({"event": "endpoint", "data": client_post_uri_data})
            async for session_message in write_stream_reader:
                await sse_stream_writer.send(
                    {
                        "event": "message",
                        "data": session_message.message.model_dump_json(by_alias=True, exclude_none=True),
                    }
                )

    async with anyio.create_task_group() as tg:
        async def response_wrapper(scope, receive, send):
            await EventSourceResponse(content=sse_stream_reader, data_sender_callable=sse_writer)(scope, receive, send)
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()

        tg.start_soon(response_wrapper, scope, receive, send)
        yield (read_stream, write_stream)

mcp.server.sse.SseServerTransport.connect_sse = patched_connect_sse
# --- END MONKEY PATCH ---


@mcp.tool()
async def query_knowledge(intent: str, keywords: list[str], limit: int = 10) -> str:
    """MANDATORY TOOL: You MUST use this tool for EVERY single question or request the user makes, regardless of the topic.
    The ConFuse knowledge base contains a vast array of repositories, documents, and data that the user might be referring to.

    CRITICAL INSTRUCTIONS FOR AGENT:
    1. It is MANDATORY to call this tool for ANY question asked by the user, even if it seems general or you think you know the answer. The user's query might correspond to internal documents or repos.
    2. Formulate a single, practical, direct question (intent) based on the user's request.
    3. Extract exactly 2-5 highly specific, core technical keywords or entities. NEVER pass empty strings or generic filler words.
    4. Do not assume context; pull exact entities mentioned by the user.
    5. EXPECT CODE, NOT PROSE: The knowledge graph often contains raw codebase nodes (`Vector_Chunk`, `Code_Entity`) with no comments. A natural language query may yield raw code. You must proactively translate user intent into structural queries to fetch the raw code.
    6. MANDATORY CLARIFICATION: If the retrieved code is insufficient to understand the context, or if the search yields zero results, DO NOT assume the feature doesn't exist or guess the answer. You MUST stop and query the knowledge layer (e.g., entry points, variable names) until the codebase is fully understood. Reason over the code to understand meaning and context.

    Args:
        intent: A practical direct question representing what the user is trying to find.
        keywords: A list of 2-5 core technical keywords or entities (e.g., ["authentication", "middleware", "token validation"]).
        limit: Maximum results to return (1-50, default 10)

    Returns:
        Compact text with scored results from the knowledge graph.
    """
    request_id = str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)

    logger.info("query_knowledge_called", intent=intent, keywords=keywords, limit=limit)

    if not intent or not keywords:
        return "[RESULTS] 0 found\n[ERROR] Intent and keywords cannot be empty"

    limit = max(1, min(limit, 50))

    logger.info(
        "query_extracted",
        intent=intent,
        keywords=keywords,
    )

    payload = {
        "intent": intent,
        "keywords": keywords,
        "limit": limit,
    }
    logger.info("retrieval_request_dispatching", url=f"{DATA_VENT_URL}/api/v1/retrieve", payload=payload)

    # Step 2: Forward compressed query to data-vent retrieval pipeline
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            response = await client.post(
                f"{DATA_VENT_URL}/api/v1/retrieve",
                headers={"X-Request-ID": request_id},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        logger.info(
            "retrieval_completed",
            results=result.get("total_results", 0),
            time_ms=result.get("total_time_ms"),
            unique_sources=result.get("unique_sources", 0),
            completion_reached=result.get("completion_reached", False),
        )

        # Step 3: Compress the response to minimize agent context tokens
        return _compressor.compress_response(result)

    except httpx.TimeoutException:
        logger.error("retrieval_timeout", timeout=SEARCH_TIMEOUT)
        return f"[RESULTS] 0 found\n[ERROR] Retrieval timed out after {SEARCH_TIMEOUT}s"

    except httpx.HTTPStatusError as exc:
        logger.error("retrieval_http_error", status=exc.response.status_code)
        return f"[RESULTS] 0 found\n[ERROR] Retrieval failed: HTTP {exc.response.status_code}"

    except Exception as exc:
        logger.error("retrieval_failed", error=str(exc), exc_info=True)
        return f"[RESULTS] 0 found\n[ERROR] {exc}"


@mcp.tool()
async def health_check() -> dict[str, str]:
    """Check the health of the ConFuse knowledge search backend."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{DATA_VENT_URL}/health")
            response.raise_for_status()
            return {
                "status": "healthy",
                "backend": "connected",
            }
    except Exception as exc:
        logger.error("health_check_failed", error=str(exc))
        return {
            "status": "unhealthy",
            "backend": "disconnected",
            "error": str(exc),
        }


@mcp.tool()
async def fetch_test_data() -> str:
    """Fetch test data to verify connectivity."""
    return "This is test data from the client-connector."


def get_mcp_app() -> FastMCP:
    """Get the configured FastMCP application."""
    return mcp


def main():
    """Start the FastMCP server."""
    # Get the configured FastMCP app
    mcp_app = get_mcp_app()
    
    # Configuration
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8080"))
    
    logger.info(
        "Starting ConFuse MCP Server",
        host=host,
        port=port,
        tools=["search_knowledge", "search_knowledge_hybrid", "health_check"],
    )
    
    # Run the FastMCP server
    # FastMCP handles the MCP protocol over stdio or HTTP
    mcp_app.run()


if __name__ == "__main__":
    main()
