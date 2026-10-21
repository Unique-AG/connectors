<!-- mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00 -->
# Architecture Demo MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

## Commands

```bash
# install
uv sync
# every check CI runs, in its order
bash ../../scripts/check-python-service.sh .
# or one at a time
uv run ruff format . && uv run ruff check .
uv run basedpyright
uv run lint-imports
uv run pytest
# serve on http://127.0.0.1:8000/mcp, after cp .env.example .env
uv run architecture-demo-mcp
```

## This MCP

Reference MCP showing every scaffold layer against Tiingo market data: OpenAPI operations served as tools, a Redis-cached price performance summary and a Postgres portfolio, behind Zitadel sign-in.

- Upstream: OpenAPI, from the vendor's spec in `upstream/openapi.yml`. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.
- Persistence: Postgres through SQLAlchemy, as `Persistence.database`. Models subclass `persistence.Base`; `uv run alembic revision --autogenerate -m '...'` writes a migration, which the chart's migration hook applies. Redis as a key-value store (`py-key-value-aio`), as `Persistence.store`.
- Auth: Zitadel sign-in through `unique_mcp`'s OIDC proxy, built in `mcp/auth/` and passed to `FastMCP(auth=...)`. Its clients and tokens sit encrypted in Redis. `get_owner` in `mcp/dependencies.py` reads the caller's subject, which tools pass to contexts as a plain `owner` string. `MCP_AUTH_MODE=none` turns sign-in off, and `run_server` then keeps the server on loopback.
- The example: `contexts/prices` (a Redis-cached price history behind `get_price_performance`) and `contexts/portfolios` (`record_position`, which writes to Postgres and values the portfolio through the `prices` feature). `README.md` maps each tool to what it shows.
