# Architecture Demo MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: `uv run pytest` checks most of it, and
`services/architecture-demo-mcp` holds a worked example of every part.

## Commands

```bash
# install
uv sync
# tests, contracts and folder rules
uv run pytest
uv run ruff format . && uv run ruff check .
uv run basedpyright
# serve on http://127.0.0.1:8000/mcp, after cp .env.example .env
uv run architecture-demo-mcp
```

## This MCP

Reference MCP showing every scaffold layer: Tiingo market data through OpenAPI, with Postgres and Redis persistence. Copy its patterns; do not deploy it.

- Upstream: OpenAPI, from the vendor's spec in `upstream/openapi.yml`. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.
- Persistence: Postgres through SQLAlchemy, as `Persistence.database`. Models subclass `persistence.Base`; `uv run alembic revision --autogenerate -m '...'` writes a migration, which the chart's migration hook applies. Redis as a key-value store (`py-key-value-aio`), as `Persistence.store`.
- Auth: Not implemented. `run_server` refuses to serve beyond loopback until the server has an auth provider, `FastMCP(auth=...)`. The `new-mcp` skill's rules for coding auth say how to add one.
