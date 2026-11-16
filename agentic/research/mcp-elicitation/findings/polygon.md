# Massive.com MCP Server (formerly Polygon.io `mcp_polygon`)

| Field | Value |
|---|---|
| Vendor | Massive.com (Polygon.io rebranded); official |
| Category | market-data |
| Tier | 2 |
| Source | open (https://github.com/massive-com/mcp_massive @ 1e161a8; `polygon-io/mcp_polygon` redirects here, same HEAD) |
| Language / SDK | Python, `mcp>=1.27.0` (uv.lock pins `mcp` 1.27.0, FastMCP from the official SDK) |
| Hosted endpoint | https://mcp.massive.com (hosted build; not reviewed, may differ from this repo) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` in the repo.

## Fallback without client elicitation support

Not applicable. The API key comes from `MASSIVE_API_KEY` at startup; a missing key makes `call_api` return the text "Error [AUTH]: MASSIVE_API_KEY is not set." ([server.py#L354-L356](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/server.py#L354-L356)).

## Other human-in-the-loop mechanisms

- The server is read-only by construction: three tools, `search_endpoints`, `call_api`, `query_data`, all annotated `ToolAnnotations(readOnlyHint=True)` ([server.py#L196](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/server.py#L196), [#L290](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/server.py#L290), [#L457](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/server.py#L457)).
- `call_api` only reaches paths in an endpoint allowlist built from the index, and rejects path traversal and embedded query strings.
- `query_data` runs SQL against an in-memory SQLite store and only allows one read-only `SELECT` over registered tables, enforced by a sqlglot AST check plus a SQLite authorizer ([store.py#L863](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/store.py#L863)).
- No confirmation needed: nothing writes to the upstream account.

## Notes

- `call_api` takes an optional `api_key` argument ("API key for this request. Overrides the server's default key.") ([server.py#L318-L324](https://github.com/massive-com/mcp_massive/blob/1e161a8c50b69bd467b092e0721e30908ab94eb6/src/mcp_massive/server.py#L318-L324)). That routes a secret through the model's context, which form-mode `secret-input` elicitation exists to avoid.
- The repo has collapsed one-tool-per-endpoint into search/call/query, so there is no per-endpoint missing-parameter prompting either; the model is expected to discover parameters via `search_endpoints`.
