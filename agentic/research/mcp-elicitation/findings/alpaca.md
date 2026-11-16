# Alpaca MCP Server (v2)

| Field | Value |
|---|---|
| Vendor | Alpaca; official |
| Category | trading |
| Tier | 1 |
| Source | open (https://github.com/alpacahq/alpaca-mcp-server @ 9daa38c) |
| Language / SDK | Python, `fastmcp==3.4.7` (uv.lock), `mcp` 1.26.0 |
| Hosted endpoint | none (stdio by default; optional streamable-http/SSE bound to localhost, no MCP auth) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `ctx.elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state`. Most tools are generated with `FastMCP.from_openapi` from bundled Alpaca specs ([server.py#L176-L202](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/server.py#L176-L202)). The only hand-written trading tools are the three order-placement overrides, and none of them takes a `Context`.

## Fallback without client elicitation support

Not applicable. `place_stock_order`, `place_crypto_order`, `place_option_order`, `close_all_positions`, `cancel_all_orders` and `exercise_options_position` all run immediately.

## Other human-in-the-loop mechanisms

- **Paper trading by default.** `ALPACA_PAPER_TRADE` defaults to `"true"`, which points the server at `paper-api.alpaca.markets`. Live trading needs an explicit `false` ([server.py#L116-L118](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/server.py#L116-L118)). This is the main safety net.
- **Toolset allowlist.** `ALPACA_TOOLSETS` (comma-separated, e.g. `stock-data,crypto-data`) limits the exposed tools to listed toolsets. Each toolset is an explicit operationId allowlist, so new API endpoints stay excluded by default ([toolsets.py](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/toolsets.py), [server.py#L80-L88](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/server.py#L80-L88)). The default is all toolsets.
- **Annotations, partial.** The order overrides declare `readOnlyHint: False, destructiveHint: True, idempotentHint: False` ([overrides.py#L61-L69](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/overrides.py#L61-L69)). Market-data overrides and doc tools are marked read-only. The OpenAPI-generated tools, including `close_all_positions`, `cancel_all_orders` and `close_position`, get **no annotations**: the `mcp_component_fn` customizer only rewrites the description ([server.py#L91-L98](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/server.py#L91-L98)). We checked FastMCP 4.1.5's OpenAPI provider, which passes no annotations to `OpenAPITool`. We assume 3.4.7 behaves the same; not verified.
- **Trust-boundary middleware.** Every tool result is wrapped in a `{_alpaca_mcp_security, data}` envelope that tells the model to treat the data as untrusted ([security.py#L84-L104](https://github.com/alpacahq/alpaca-mcp-server/blob/9daa38cc41d2327467b8dd83cceb06b457074cbc/src/alpaca_mcp_server/security.py#L84-L104)). This guards against prompt injection rather than adding human approval.
- README: HTTP transport binds to `127.0.0.1` with Host/Origin checks, "This package does not configure MCP OAuth, so do not expose it directly to the public internet."

## Notes

- A trading server that can liquidate a whole portfolio in one call (`close_all_positions`) relies on paper mode and the client's own tool-approval UI. It has no server-side confirmation and no destructive hint on that tool.
