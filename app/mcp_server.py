"""
MCP Server — ConFuse Knowledge Search

Exposes a single MCP tool (query_knowledge) to AI agents.
Accepts natural-language queries, compresses them via PromptCompressor,
forwards to data-vent for retrieval, and compresses the response
before returning it to the agent.
"""

import os
from typing import Any

import httpx
import structlog
from mcp.server.fastmcp import FastMCP

from app.services.prompt_compressor import PromptCompressor

logger = structlog.get_logger()

# Initialize FastMCP server
mcp = FastMCP("ConFuse Knowledge Search")

# data-vent retrieval service
DATA_VENT_URL = os.getenv("DATA_VENT_URL", "http://localhost:3005")
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT_SECS", "30"))

# Shared compressor instance
_compressor = PromptCompressor()


@mcp.tool()
async def query_knowledge(query: str, limit: int = 10) -> str:
    """Search the ConFuse knowledge base.

    Accepts a natural-language question or keyword query and returns
    matching knowledge chunks from your organization's code, docs,
    and internal documents.

    Args:
        query: Natural-language search query
              (e.g., "How does the authentication middleware validate tokens?")
        limit: Maximum results to return (1-50, default 10)

    Returns:
        Compact text with scored results from the knowledge graph.
    """
    logger.info("query_knowledge_called", query=query, limit=limit)

    if not query or not query.strip():
        return "[RESULTS] 0 found\n[ERROR] Query cannot be empty"

    limit = max(1, min(limit, 50))

    # Step 1: Compress the natural-language prompt into search keywords
    compressed = _compressor.compress_query(query)

    logger.info(
        "query_compressed",
        original=query[:80],
        compressed=compressed.compressed[:80],
        keywords=compressed.keywords[:10],
    )

    # Step 2: Forward compressed query to data-vent retrieval pipeline
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            response = await client.post(
                f"{DATA_VENT_URL}/api/v1/retrieve",
                json={
                    "query": compressed.compressed,
                    "limit": limit,
                },
            )
            response.raise_for_status()
            result = response.json()

        logger.info(
            "retrieval_completed",
            results=result.get("total_results", 0),
            time_ms=result.get("total_time_ms"),
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
