<!-- mcp-scaffold-commit: 5264f9f14505, timestamp: 2026-11-02T00:13:01+00:00 -->
# Space Config MCP

@../../packages/mcp-architecture/ARCHITECTURE.md

This MCP keeps the architecture every Python MCP in this repo shares. Read
[`packages/mcp-architecture/ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md)
before you write code here: ruff, basedpyright and import-linter check most of it.

Its [Commands](../../packages/mcp-architecture/ARCHITECTURE.md#commands) install, check and
serve this MCP, with `space-config-mcp` for `<name>`.

## This MCP

Read and update Unique AI space and module configuration

- Upstream: A client of our own in `upstream/client.py`, started from the scaffold's HTTP client: one `request` for any method and path, retried by `RetrySettings`, parsing every body into a pydantic model. The `new-mcp` skill's rules for coding a client apply.
- Persistence: None.
- Auth: Not implemented. `run_server` refuses to serve beyond loopback until the server has an auth provider, `FastMCP(auth=...)`. The `new-mcp` skill's rules for coding auth say how to add one.
