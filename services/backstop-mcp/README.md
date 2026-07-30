# backstop-mcp

Backstop CRM FastMCP server with OAuth credential bridging.

## Run locally

```bash
cd services/backstop-mcp
cp .env.example .env   # fill BACKSTOP_MCP_ENCRYPTION_KEY and DB_*
uv sync
uv run backstop-mcp
```

- Probe: `GET http://localhost:9010/probe`
- Health: `GET http://localhost:9010/health`
- Metrics: `GET http://localhost:9010/metrics`
- MCP: `http://localhost:9010/mcp` (HTTP transport)

## Migrations

```bash
uv run alembic upgrade head
```

## Tests

```bash
uv run pytest
```
