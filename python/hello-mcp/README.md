# hello-mcp

Minimal no-auth FastMCP Hello World server.

## Run locally

```bash
cd python/hello-mcp
uv sync
uv run hello-mcp
```

- Probe: `GET http://localhost:8000/probe` → `{"status":"ok"}`
- MCP: `http://localhost:8000/mcp` (HTTP transport)

## Tool

`hello(name: str) -> str` returns `Hello, {name}!`

## Tests

```bash
uv run pytest
```
