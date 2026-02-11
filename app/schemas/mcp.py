"""MCP Protocol types for JSON-RPC communication."""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request."""

    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC error object."""

    code: int
    message: str
    data: Any | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcError | None = None


class ToolInputSchema(BaseModel):
    """JSON Schema for tool input."""

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class Tool(BaseModel):
    """MCP Tool definition."""

    name: str
    description: str
    inputSchema: ToolInputSchema = Field(default_factory=ToolInputSchema)


class Resource(BaseModel):
    """MCP Resource definition."""

    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None


class ResourceContent(BaseModel):
    """Content of a resource."""

    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None  # base64 encoded


class ToolCallRequest(BaseModel):
    """Request to call a tool."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """Result of a tool call."""

    content: list[dict[str, Any]]
    isError: bool = False


class ClientInfo(BaseModel):
    """Information about the connecting client."""

    name: str
    version: str


class ServerInfo(BaseModel):
    """Server information returned on initialize."""

    name: str = "ConHub MCP Gateway"
    version: str = "1.0.0"


class Capabilities(BaseModel):
    """MCP capabilities."""

    resources: dict[str, bool] = Field(default_factory=lambda: {"subscribe": False, "listChanged": False})
    tools: dict[str, bool] = Field(default_factory=lambda: {"listChanged": False})
    prompts: dict[str, bool] = Field(default_factory=lambda: {"listChanged": False})
    logging: dict[str, Any] = Field(default_factory=dict)


class InitializeResult(BaseModel):
    """Result of initialize request."""

    protocolVersion: str = "2024-11-05"
    capabilities: Capabilities = Field(default_factory=Capabilities)
    serverInfo: ServerInfo = Field(default_factory=ServerInfo)


class ConnectionState(str, Enum):
    """State of an MCP connection."""

    CONNECTING = "connecting"
    INITIALIZING = "initializing"
    READY = "ready"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"
