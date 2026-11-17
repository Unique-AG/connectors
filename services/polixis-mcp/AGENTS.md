<!-- mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00 -->
# Polixis MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

Its [Commands](../../packages/mcp-architecture/ARCHITECTURE.md#commands) install, check and
serve this MCP, with `polixis-mcp` for `<name>`.

## This MCP

Looks up organizations and people in Polixis corporate data: search, corporate profiles with their related parties, relationship graphs, top-down ownership and ultimate beneficial owners, and sanctions and PEP flags.

- Upstream: OpenAPI. `upstream/openapi.yml` is not the vendor's: Polixis had no working spec, so it was written from their PDF documentation (v3), with every response field optional and fields of unknown shape left out. When their spec arrives, it replaces this file; see "Switching to the vendor's spec" in `README.md`. The client exchanges `UPSTREAM_CLIENT_ID` and `UPSTREAM_CLIENT_SECRET` for a bearer token at `UPSTREAM_TOKEN_URL` and sends `UPSTREAM_API_KEY` as `x-api-key` on every request. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`. Generate an operation and its models with `uv run poe codegen` before writing either by hand; [`guides/upstream.md`](../../packages/mcp-architecture/guides/upstream.md#openapi) says when a hand-written model is allowed.
- Persistence: Postgres as a key-value store (`py-key-value-aio`, its table made on first use, no migrations), as `Persistence.store`, for the Zitadel sign-in state (`DATABASE_URL`). No Polixis data is stored.
- Auth: Zitadel sign-in through `unique_mcp`'s OIDC proxy, built in `mcp/auth/` and passed to `FastMCP(auth=...)`. Its clients and tokens sit encrypted in Postgres. `MCP_AUTH_MODE=none` turns sign-in off, and `run_server` then keeps the server on loopback. The Polixis credentials are not that sign-in: every admitted caller shares them.
