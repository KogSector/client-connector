"""Main entry point for FastMCP-based client-connector.

This module starts the FastMCP server that exposes knowledge search tools
to AI agents via the Model Context Protocol.
"""

import asyncio
import os

import structlog
import uvicorn
from mcp.server.fastmcp import FastMCP

from app.mcp_server import get_mcp_app

logger = structlog.get_logger()


def main():
    """Start the FastMCP server."""
    # Get the configured FastMCP app
    mcp_app = get_mcp_app()
    
    # Configuration
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    
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
