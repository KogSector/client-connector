"""Gateway module."""

from .mcp_client import McpClient, get_mcp_client, shutdown_mcp_client
from .toggle_client import FeatureToggleClient, get_toggle_client, is_feature_enabled

__all__ = [
    "McpClient",
    "get_mcp_client",
    "shutdown_mcp_client",
    "FeatureToggleClient",
    "get_toggle_client",
    "is_feature_enabled",
]
