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

- Upstream: OpenAPI, from the vendor's spec in `upstream/openapi.yml`. `upstream/routes.py` lists the operations served as tools straight from the spec, and `operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.
- Persistence: None.
- Auth: Not implemented. `run_server` refuses to serve beyond loopback until the server has an auth provider, `FastMCP(auth=...)`. The `new-mcp` skill's rules for coding auth say how to add one.
