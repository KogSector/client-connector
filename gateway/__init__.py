"""Gateway module."""

from .mcp_client import McpClient, get_mcp_client, shutdown_mcp_client

__all__ = [
    "McpClient",
    "get_mcp_client",
    "shutdown_mcp_client",
]
