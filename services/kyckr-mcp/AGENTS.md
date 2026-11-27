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
- Persistence: Postgres as a key-value store (`py-key-value-aio`, its table made on first use, no migrations), for the Zitadel sign-in state only (`DATABASE_URL`), so `Persistence` is empty. The Kyckr key is never stored.
- Auth: Zitadel sign-in through `mcp-zitadel`, built in `mcp/auth/` and passed to `FastMCP(auth=...)`. Its clients and tokens sit encrypted in Postgres. `MCP_AUTH_MODE=none` turns sign-in off, and `run_server` then keeps the server on loopback. With `ZITADEL_ORG_ID`, `IdTokenVerifier` refuses every id token of another organisation. The Kyckr key (`UPSTREAM_API_KEY`) is not that sign-in: every admitted caller shares it.
