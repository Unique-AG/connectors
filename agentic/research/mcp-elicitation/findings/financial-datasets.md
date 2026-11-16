# Financial Datasets MCP Server

| Field | Value |
|---|---|
| Vendor | Financial Datasets; official |
| Category | market-data |
| Tier | 2 |
| Source | open (https://github.com/financial-datasets/mcp-server @ 08e7a3d) |
| Language / SDK | Python, `mcp[cli]>=1.3.0` (uv.lock pins `mcp` 1.3.0, FastMCP from the official SDK) |
| Hosted endpoint | none in this repo |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. The whole server is one file, [server.py](https://github.com/financial-datasets/mcp-server/blob/08e7a3dbb949d3d99bbd6d6f3a22e5f02973ec58/server.py). No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state`. The locked SDK (`mcp` 1.3.0) predates `Context.elicit` (added in 1.10.0), so elicitation was not possible with this lockfile.

## Fallback without client elicitation support

Not applicable. `FINANCIAL_DATASETS_API_KEY` is read from the environment / `.env` on every request ([server.py#L26-L32](https://github.com/financial-datasets/mcp-server/blob/08e7a3dbb949d3d99bbd6d6f3a22e5f02973ec58/server.py#L26-L32)). With no key the request goes out unauthenticated and the HTTP error text is returned as `{"Error": ...}`.

## Other human-in-the-loop mechanisms

None needed and none present. All 11 tools are GET-only market data reads (statements, prices, news, crypto); no annotations, no confirm arguments, no read-only flag.

## Notes

- Last commit is June 2025; the repo looks unmaintained relative to the spec (no annotations, SDK 1.3.0).
