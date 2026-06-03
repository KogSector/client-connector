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


@mcp.tool()
async def query_knowledge(intent: str, keywords: list[str], limit: int = 10) -> str:
    """Search the ConFuse knowledge base.

    Extract the core technical intent and keywords from the user's prompt 
    before querying the knowledge base. Do NOT pass raw natural language.

    Args:
        intent: A short 1-sentence summary of what the user is trying to find.
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

    # We now trust the LLM agent to do the summarization and keyword extraction
    compressed_query = " ".join(keywords)

    logger.info(
        "query_extracted",
        intent=intent,
        compressed=compressed_query,
        keywords=keywords,
    )

    payload = {
        "query": compressed_query,
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
