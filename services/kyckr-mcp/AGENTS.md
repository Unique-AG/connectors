<!-- mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00 -->
# Kyckr MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

Its [Commands](../../packages/mcp-architecture/ARCHITECTURE.md#commands) install, check and
serve this MCP, with `kyckr-mcp` for `<name>`.

## This MCP

Search company registries and order registry documents through Kyckr for KYC and KYB workflows.

- Upstream: OpenAPI, from the vendor's spec in `upstream/openapi.yml`. No operation is served straight from the spec: `operation-ids` in `[tool.mcp-openapi]` lists the ones our tools call through `Upstream`. Generate an operation and its models with `uv run poe codegen` before writing either by hand; [`guides/upstream.md`](../../packages/mcp-architecture/guides/upstream.md#openapi) says when a hand-written model is allowed.
- Persistence: Postgres through SQLAlchemy, as `Persistence.database`. Models subclass `persistence.Base`; `uv run alembic revision --autogenerate -m '...'` writes a migration, which the chart's migration hook applies.
- Auth: Not implemented. `run_server` refuses to serve beyond loopback until the server has an auth provider, `FastMCP(auth=...)`. The `new-mcp` skill's rules for coding auth say how to add one.
