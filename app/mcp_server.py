"""FastMCP-based MCP Server for ConFuse Knowledge Search.

This module implements the MCP server using FastMCP that exposes knowledge search
tools to AI agents. It communicates with the backend mcp-server service for
FalcorDB vector search operations.
"""

import os
from typing import Any

import httpx
import structlog
from mcp.server.fastmcp import FastMCP

logger = structlog.get_logger()

# Initialize FastMCP server
mcp = FastMCP("ConFuse Knowledge Search")

# Backend service URL (mcp-server that does FalcorDB search)
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:3004")
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT_SECS", "30"))


@mcp.tool()
async def search_knowledge(
    query: str,
    workspace_id: str | None = None,
    limit: int = 10,
    similarity_threshold: float = 0.75,
) -> dict[str, Any]:
    """Search the knowledge base using semantic vector search.
    
    This tool searches through your organization's knowledge base including:
    - Code repositories
    - Documentation
    - API specifications
    - Internal documents
    
    The search uses semantic understanding to find relevant information even if
    the exact keywords don't match.
    
    Args:
        query: The search query or question (e.g., "How does authentication work?")
        workspace_id: Optional workspace ID to filter results
        limit: Maximum number of results to return (default: 10, max: 50)
        similarity_threshold: Minimum similarity score (0.0-1.0, default: 0.75)
    
    Returns:
        Dictionary containing:
        - results: List of matching knowledge chunks with text, source, and scores
        - total: Total number of results found
        - query_info: Information about the search query
    
    Example:
        >>> await search_knowledge("authentication flow", limit=5)
        {
            "results": [
                {
                    "text": "Authentication uses JWT tokens...",
                    "source": "docs/auth.md",
                    "similarity_score": 0.92,
                    "chunk_index": 0
                }
            ],
            "total": 5,
            "query_info": {...}
        }
    """
    logger.info(
        "Knowledge search requested",
        query=query,
        workspace_id=workspace_id,
        limit=limit,
        threshold=similarity_threshold,
    )
    
    # Validate inputs
    if not query or not query.strip():
        return {
            "error": "Query cannot be empty",
            "results": [],
            "total": 0,
        }
    
    if limit < 1 or limit > 50:
        limit = min(max(limit, 1), 50)
        logger.warning("Limit adjusted to valid range", adjusted_limit=limit)
    
    if similarity_threshold < 0.0 or similarity_threshold > 1.0:
        similarity_threshold = 0.75
        logger.warning(
            "Threshold adjusted to valid range",
            adjusted_threshold=similarity_threshold,
        )
    
    try:
        # Call backend mcp-server for FalcorDB vector search
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            response = await client.post(
                f"{MCP_SERVER_URL}/api/v1/search/semantic",
                json={
                    "query": query,
                    "workspace_id": workspace_id,
                    "limit": limit,
                    "similarity_threshold": similarity_threshold,
                },
            )
            response.raise_for_status()
            
            search_results = response.json()
            
            logger.info(
                "Knowledge search completed",
                query=query,
                results_count=len(search_results.get("results", [])),
                total=search_results.get("total", 0),
            )
            
            return search_results
    
    except httpx.TimeoutException:
        logger.error("Search timeout", query=query, timeout=SEARCH_TIMEOUT)
        return {
            "error": f"Search timed out after {SEARCH_TIMEOUT} seconds",
            "results": [],
            "total": 0,
        }
    
    except httpx.HTTPStatusError as e:
        logger.error(
            "Search HTTP error",
            query=query,
            status_code=e.response.status_code,
            error=str(e),
        )
        return {
            "error": f"Search failed: {e.response.status_code}",
            "results": [],
            "total": 0,
        }
    
    except Exception as e:
        logger.error("Search failed", query=query, error=str(e), exc_info=True)
        return {
            "error": f"Search failed: {str(e)}",
            "results": [],
            "total": 0,
        }


@mcp.tool()
async def search_knowledge_hybrid(
    query: str,
    workspace_id: str | None = None,
    limit: int = 10,
    include_related: bool = True,
    max_depth: int = 2,
) -> dict[str, Any]:
    """Search knowledge base using hybrid search (vector + graph traversal).
    
    This advanced search combines semantic vector search with knowledge graph
    traversal to find not just similar content, but also related information
    through document relationships, entity connections, and temporal links.
    
    Args:
        query: The search query or question
        workspace_id: Optional workspace ID to filter results
        limit: Maximum number of results to return (default: 10, max: 50)
        include_related: Whether to include graph-related chunks (default: True)
        max_depth: Maximum graph traversal depth (default: 2, max: 3)
    
    Returns:
        Dictionary containing:
        - results: List of matching knowledge with vector and graph scores
        - related_entities: Entities found in the results
        - graph_connections: Relationship information
        - total: Total number of results
    
    Example:
        >>> await search_knowledge_hybrid("user authentication", include_related=True)
        {
            "results": [
                {
                    "text": "User authentication flow...",
                    "vector_score": 0.89,
                    "graph_score": 0.76,
                    "combined_score": 0.85,
                    "related_chunks": [...]
                }
            ],
            "related_entities": ["JWT", "OAuth", "Session"],
            "total": 8
        }
    """
    logger.info(
        "Hybrid knowledge search requested",
        query=query,
        workspace_id=workspace_id,
        limit=limit,
        include_related=include_related,
        max_depth=max_depth,
    )
    
    # Validate inputs
    if not query or not query.strip():
        return {
            "error": "Query cannot be empty",
            "results": [],
            "total": 0,
        }
    
    if limit < 1 or limit > 50:
        limit = min(max(limit, 1), 50)
    
    if max_depth < 1 or max_depth > 3:
        max_depth = min(max(max_depth, 1), 3)
    
    try:
        # Call backend mcp-server for hybrid search
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT * 2) as client:
            response = await client.post(
                f"{MCP_SERVER_URL}/api/v1/search/hybrid",
                json={
                    "query": query,
                    "workspace_id": workspace_id,
                    "limit": limit,
                    "include_related": include_related,
                    "max_depth": max_depth,
                },
            )
            response.raise_for_status()
            
            search_results = response.json()
            
            logger.info(
                "Hybrid search completed",
                query=query,
                results_count=len(search_results.get("results", [])),
                entities_count=len(search_results.get("related_entities", [])),
            )
            
            return search_results
    
    except httpx.TimeoutException:
        logger.error("Hybrid search timeout", query=query)
        return {
            "error": f"Hybrid search timed out after {SEARCH_TIMEOUT * 2} seconds",
            "results": [],
            "total": 0,
        }
    
    except httpx.HTTPStatusError as e:
        logger.error(
            "Hybrid search HTTP error",
            query=query,
            status_code=e.response.status_code,
        )
        return {
            "error": f"Hybrid search failed: {e.response.status_code}",
            "results": [],
            "total": 0,
        }
    
    except Exception as e:
        logger.error("Hybrid search failed", query=query, error=str(e), exc_info=True)
        return {
            "error": f"Hybrid search failed: {str(e)}",
            "results": [],
            "total": 0,
        }


# Health check for the MCP server
@mcp.tool()
async def health_check() -> dict[str, str]:
    """Check the health status of the knowledge search service.
    
    Returns:
        Dictionary with status information
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{MCP_SERVER_URL}/health")
            response.raise_for_status()
            
            return {
                "status": "healthy",
                "backend": "connected",
                "message": "Knowledge search service is operational",
            }
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        return {
            "status": "unhealthy",
            "backend": "disconnected",
            "message": f"Backend service unavailable: {str(e)}",
        }


# Export the FastMCP app
def get_mcp_app() -> FastMCP:
    """Get the configured FastMCP application."""
    return mcp
