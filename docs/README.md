# Client Connector Documentation

## Overview

The client-connector is a **gateway service** that enables AI agents to connect to ConFuse remotely. It provides WebSocket and HTTP+SSE transports, handles authentication, rate limiting, and session management.

## Role in ConFuse

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AI AGENTS                                   │
│       Cursor  │  Windsurf  │  Claude  │  VS Code  │  Custom          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ WebSocket / HTTP+SSE
                                │
┌───────────────────────────────┼─────────────────────────────────────┐
│                               ▼                                      │
│               CLIENT-CONNECTOR (This Service)                        │
│                        Port: 8095                                    │
│                                                                      │
│   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐              │
│   │  Transport  │   │    Auth     │   │   Session   │              │
│   │   Layer     │   │   Layer     │   │   Manager   │              │
│   │             │   │             │   │             │              │
│   │ • WebSocket │   │ • JWT       │   │ • Tracking  │              │
│   │ • HTTP+SSE  │   │ • API Key   │   │ • Expiry    │              │
│   │             │   │ • Rate Limit│   │ • Cache     │              │
│   └─────────────┘   └─────────────┘   └─────────────┘              │
│                                                                      │
│                     ┌─────────────┐                                 │
│                     │   Gateway   │                                 │
│                     │             │                                 │
│                     │ • Route     │                                 │
│                     │ • Validate  │                                 │
│                     │ • Forward   │                                 │
│                     └──────┬──────┘                                 │
└────────────────────────────┼────────────────────────────────────────┘
                             │ subprocess (stdio) / HTTP
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          MCP-SERVER                                  │
│                          Port: 3004                                  │
│              MCP Protocol  •  Connectors  •  Tools                  │
└─────────────────────────────────────────────────────────────────────┘
```

## Why client-connector?

The MCP protocol traditionally uses **stdio** (subprocess), which requires the agent to spawn the MCP server locally. client-connector enables:

1. **Remote connections**: Agents connect over the network
2. **Multi-tenant**: Multiple users share the same infrastructure
3. **Authentication**: JWT/API key enforcement
4. **Rate limiting**: Prevent abuse
5. **Session management**: Track connected clients

## Transport Options

### 1. WebSocket (Recommended)

Full-duplex communication, best for IDEs.

```javascript
const ws = new WebSocket('wss://api.confuse.io/mcp/ws?key=YOUR_API_KEY');

ws.onopen = () => {
  // Initialize
  ws.send(JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: { clientInfo: { name: "MyAgent", version: "1.0" } }
  }));
};

ws.onmessage = (event) => {
  const response = JSON.parse(event.data);
  console.log(response);
};
```

### 2. HTTP+SSE (Planned)

For environments where WebSocket isn't available:
- POST requests to `/mcp/message`
- SSE stream from `/mcp/sse` for responses

## Authentication

### JWT Token

Pass in WebSocket URL:
```
ws://localhost:8095/mcp/ws?token=eyJhbGc...
```

Or in header for HTTP:
```
Authorization: Bearer eyJhbGc...
```

### API Key

Pass in WebSocket URL:
```
ws://localhost:8095/mcp/ws?key=key_live_xxx
```

Or in header for HTTP:
```
X-API-Key: key_live_xxx
```

## API Endpoints

### MCP Endpoints

| Endpoint | Type | Description |
|----------|------|-------------|
| `/mcp/ws` | WebSocket | Full MCP protocol over WebSocket |
| `/mcp/sse` | GET | SSE stream for responses (planned) |
| `/mcp/message` | POST | Send MCP request (planned) |

### Management Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Service health check |
| `/admin/sessions` | GET | List active sessions |
| `/admin/stats` | GET | Service statistics |

## Session Lifecycle

```
┌─────────────────────────────────────────────────────────────────────┐
│                      SESSION LIFECYCLE                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   CONNECTING ──────> INITIALIZING ──────> READY ──────> CLOSED      │
│        │                   │                 │              ▲        │
│        │                   │                 │              │        │
│        │                   ▼                 │              │        │
│        └──────────────> ERROR ───────────────┴──────────────┘        │
│                                                                      │
│   States:                                                            │
│   • CONNECTING: WebSocket handshake in progress                     │
│   • INITIALIZING: Waiting for MCP initialize request                │
│   • READY: Fully connected, can process requests                    │
│   • CLOSING: Graceful disconnect in progress                        │
│   • CLOSED: Connection terminated                                   │
│   • ERROR: Connection error occurred                                │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Server port | `8095` |
| `MCP_SERVER_MODE` | `subprocess` or `http` | `subprocess` |
| `MCP_SERVER_PATH` | Path to mcp-server binary | Required for subprocess |
| `MCP_SERVER_URL` | URL of mcp-server | Required for http mode |
| `AUTH_MIDDLEWARE_URL` | Auth service URL | `http://localhost:3001` |
| `JWT_SECRET` | JWT signing secret | Required |
| `RATE_LIMIT_PER_MINUTE` | Max requests/min | `60` |
| `MAX_CONCURRENT_CLIENTS` | Max connections | `100` |
| `SESSION_TIMEOUT_MINUTES` | Idle session timeout | `60` |

## MCP Server Communication

### Subprocess Mode (Default)

client-connector spawns mcp-server as a child process and communicates via stdio:

```
client-connector ──── stdin/stdout ────> mcp-server (subprocess)
```

Advantages:
- Simple setup
- No network hop
- Process isolation

### HTTP Mode

client-connector calls mcp-server via HTTP:

```
client-connector ──── HTTP ────> mcp-server (separate process)
```

Advantages:
- Separate scaling
- mcp-server can be restarted independently
- Multiple client-connectors can share one mcp-server

## Rate Limiting

```python
# Default limits
RATE_LIMIT_PER_MINUTE = 60  # Requests per minute
RATE_LIMIT_BURST = 10       # Maximum burst

# Per-user tracking
# If limit exceeded, returns 429 with Retry-After header
```

## Monitoring

### Health Check

```bash
curl http://localhost:8095/health
```

Response:
```json
{
  "status": "healthy",
  "service": "client-connector",
  "mcp_server": {
    "mode": "subprocess",
    "running": true
  },
  "sessions": {
    "total_sessions": 5,
    "max_sessions": 100,
    "states": {
      "ready": 4,
      "initializing": 1
    }
  }
}
```

### Session Stats

```bash
curl -H "Authorization: Bearer <admin_token>" http://localhost:8095/admin/stats
```

## Related Services

| Service | Relationship |
|---------|--------------|
| mcp-server | Backend MCP protocol handler |
| auth-middleware | JWT and API key validation |
| api-backend | API key generation |

## Example: Connecting from Python

```python
import asyncio
import websockets
import json

async def connect_to_confuse():
    uri = "wss://api.confuse.io/mcp/ws?key=YOUR_API_KEY"
    
    async with websockets.connect(uri) as ws:
        # Initialize
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "MyBot", "version": "1.0"}}
        }))
        
        # Get response
        response = await ws.recv()
        print(f"Initialized: {response}")
        
        # Search
        await ws.send(json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "confuse.search",
                "arguments": {"query": "authentication", "limit": 5}
            }
        }))
        
        result = await ws.recv()
        print(f"Results: {result}")

asyncio.run(connect_to_confuse())
```
