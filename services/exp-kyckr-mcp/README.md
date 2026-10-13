# Experimental Kyckr MCP

This is an experimental FastMCP 4.1.0 version of the Kyckr MCP. It lives alongside `services/kyckr-mcp` for comparison, loads Kyckr's public Companies V2 OpenAPI document, and uses `FastMCP.from_openapi` to create the low-level tools.

The generated tools are overridden with the existing agent-facing workflow:

- `search_companies`
- `get_lite_profile`
- `get_enhanced_profile`
- `list_company_documents`
- `create_document_order`
- `get_order`
- `list_orders`

The generated download tool remains internal. Successful document orders call it with `format=json`, inline `documentJson`, and remove raw download links. Kyckr API errors are returned as structured `{ success: false, ... }` responses.

Runtime response validation is disabled because the public spec documents multiple legacy order shapes; the wrappers normalize those responses for the agent.

## Run

```sh
cp .env.example .env
# Set MCP_API_KEY and KYCKR_API_KEY.
uv run kyckr-mcp
```

The MCP endpoint is available at `http://127.0.0.1:9542/$MCP_API_KEY/mcp`. The shared `unique_mcp` runtime also exposes `/probe`, `/health`, and `/metrics`.

The OpenAPI document is fetched from `KYCKR_OPENAPI_URL` during startup. The default is:

`https://developer.kyckr.com/openapi/company_v2.yaml`

## Checks

```sh
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
