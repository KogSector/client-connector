# ConFuse Client Connector

MCP Gateway service for the ConFuse Knowledge Intelligence Platform. Enables remote AI agents to connect via WebSocket/HTTP.

## Overview

This service is the **agent gateway** that:
- Accepts WebSocket connections from AI agents
- Handles JWT/API key authentication
- Proxies MCP requests to mcp-server
- Manages session state and rate limiting

## Architecture

See [docs/README.md](docs/README.md) for complete architecture.

## Quick Start

```bash
# Install
pip install -e .

# Configure
cp .env.example .env

# Build mcp-server
cd ../mcp-server && cargo build --release

# Run
python -m app.main
```

## Connection

### WebSocket (Recommended)

```javascript
const ws = new WebSocket('ws://localhost:3020/mcp/ws?key=API_KEY');
```

### For IDEs

```json
{
  "mcpServers": {
    "confuse": {
      "transport": "websocket",
      "url": "wss://api.confuse.io/mcp/ws"
    }
  }
}
```

## Endpoints

| Endpoint | Type | Description |
|----------|------|-------------|
| `/mcp/ws` | WebSocket | MCP protocol |
| `/health` | GET | Health check |
| `/admin/sessions` | GET | List sessions |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 3020 | Server port |
| `MCP_SERVER_MODE` | subprocess | subprocess or http |
| `RATE_LIMIT_PER_MINUTE` | 60 | Rate limit |

## Documentation

See [docs/](docs/) folder for complete documentation.

## License

MIT - ConFuse Team