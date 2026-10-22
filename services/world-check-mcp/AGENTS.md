<!-- mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00 -->
# World Check MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

Its [Commands](../../packages/mcp-architecture/ARCHITECTURE.md#commands) install, check and
serve this MCP, with `world-check-mcp` for `<name>`.

## This MCP

Screens people and organizations in LSEG World-Check One and returns sanctions, PEP, and adverse-media results for KYC and third-party due diligence.

- Upstream: OpenAPI, from the vendor's spec in `upstream/openapi.yml`. The client exchanges the LSEG service account (`UPSTREAM_API_KEY` and `UPSTREAM_API_SECRET`) for a bearer token at `UPSTREAM_TOKEN_URL`. `Authorization` and `Date` are not tool arguments. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.
- Persistence: Redis, for Zitadel sign-in state only (`REDIS_URL`). No screening records.
- Auth: Zitadel sign-in through `unique_mcp`'s OIDC proxy, built in `mcp/auth/` and passed to `FastMCP(auth=...)`. Its clients and tokens sit encrypted in Redis. `MCP_AUTH_MODE=none` turns sign-in off, and `run_server` then keeps the server on loopback. The LSEG service account is not that sign-in: every admitted caller shares it.
