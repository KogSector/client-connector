# Client Connector

MCP Gateway service for connecting AI agents and agentic software to ConHub's knowledge layer.

## Overview

This service hosts MCP (Model Context Protocol) connections from AI clients like:
- **IDEs**: Cursor, Windsurf, VS Code (with Cline/Copilot)
- **AI Agents**: Claude, ChatGPT, custom LLM agents
- **Agentic Software**: Any MCP-compatible application

It acts as a gateway that:
1. Accepts WebSocket/HTTP connections from agents
2. Handles authentication and rate limiting
3. Proxies MCP requests to the Rust `mcp-server`
4. Manages session state for multi-turn interactions

## Architecture

```
AI Agent (Cursor, Claude, etc.)
         │
         ▼ WebSocket / HTTP+SSE
┌─────────────────────────────────┐
│     CLIENT-CONNECTOR (Python)   │
│         Port: 8095              │
├─────────────────────────────────┤
│  • Transport (WebSocket/SSE)    │
│  • Authentication (JWT/API Key) │
│  • Rate Limiting                │
│  • Session Management           │
└─────────────────────────────────┘
         │
         ▼ subprocess (stdio) or HTTP
┌─────────────────────────────────┐
│     MCP-SERVER (Rust)           │
│         Port: 3004              │
├─────────────────────────────────┤
│  • MCP Protocol (JSON-RPC 2.0)  │
│  • Connectors (GitHub, FS, etc) │
│  • Tools & Resources            │
└─────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│     KNOWLEDGE LAYER             │
├─────────────────────────────────┤
│  • embeddings (vectors)         │
│  • relation-graph (Neo4j+Zilliz)│
│  • chunker (text processing)    │
└─────────────────────────────────┘
```

## Quick Start

### 1. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your settings
```

### 3. Build mcp-server (Rust)

```bash
cd ../mcp-server
cargo build --release
```

### 4. Run the Service

```bash
# Development
python -m app.main

# Production
uvicorn app.main:app --host 0.0.0.0 --port 8095
```

## Connecting Clients

### WebSocket (Recommended for IDEs)

```javascript
const ws = new WebSocket('ws://localhost:8095/mcp/ws?key=YOUR_API_KEY');

// Send MCP initialize
ws.send(JSON.stringify({
  jsonrpc: "2.0",
  id: 1,
  method: "initialize",
  params: {
    clientInfo: { name: "MyAgent", version: "1.0" }
  }
}));

// List available tools
ws.send(JSON.stringify({
  jsonrpc: "2.0",
  id: 2,
  method: "tools/list"
}));
```

### For Cursor/Windsurf

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "conhub": {
      "transport": "websocket",
      "url": "ws://localhost:8095/mcp/ws",
      "headers": {
        "Authorization": "Bearer YOUR_JWT_TOKEN"
      }
    }
  }
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check with service status |
| `/mcp/ws` | WS | WebSocket MCP endpoint |
| `/admin/sessions` | GET | List active sessions (admin) |
| `/admin/stats` | GET | Service statistics (admin) |

## Authentication

### JWT Token

```bash
curl -H "Authorization: Bearer YOUR_JWT" http://localhost:8095/admin/stats
```

### API Key

```bash
curl -H "X-API-Key: YOUR_KEY" http://localhost:8095/admin/stats
```

For WebSocket, pass as query parameter:
- `ws://localhost:8095/mcp/ws?token=JWT_TOKEN`
- `ws://localhost:8095/mcp/ws?key=API_KEY`

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8095` | Server port |
| `MCP_SERVER_MODE` | `subprocess` | Mode: `subprocess` or `http` |
| `MCP_SERVER_PATH` | `../mcp-server/target/release/mcp-service.exe` | Path to mcp-server binary |
| `AUTH_MIDDLEWARE_URL` | `http://localhost:3001` | Auth service URL |
| `RATE_LIMIT_PER_MINUTE` | `60` | Max requests per minute |
| `MAX_CONCURRENT_CLIENTS` | `100` | Max simultaneous connections |

## Development

```bash
# Run tests
pytest

# Format code
black .

# Lint
ruff check .
```

## License

MIT