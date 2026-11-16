# Square MCP Server

| Field | Value |
|---|---|
| Vendor | Square (Block); official |
| Category | payments |
| Tier | 2 |
| Source | open (https://github.com/square/square-mcp-server @ b276734); the hosted server is closed |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` ^1.5.0 (package-lock resolves 1.9.0) |
| Hosted endpoint | https://mcp.squareup.com/mcp (OAuth; legacy `/sse`), recommended in the README; not reviewed |
| Uses elicitation | no (open code); unknown (hosted) |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state`. The SDK in the lockfile (1.9.0) predates elicitation support. The server exposes three meta-tools: `make_api_request`, `get_type_info` and `get_service_info` ([server.ts#L180](https://github.com/square/square-mcp-server/blob/b276734fe2f1e6d4990fd99c2189c5d8d280a8b8/server.ts#L180)). `make_api_request` dispatches to about 140 write methods across 38 services, including payments, refunds, payouts and gift cards.

## Fallback without client elicitation support

Not applicable. Writes run immediately.

## Other human-in-the-loop mechanisms

- **Read-only switch.** `DISALLOW_WRITES=true` makes `make_api_request` throw for any method whose generated metadata has `isWrite: true` ([server.ts#L205-L209](https://github.com/square/square-mcp-server/blob/b276734fe2f1e6d4990fd99c2189c5d8d280a8b8/server.ts#L205-L209)). The model still sees the tool and gets an error naming the env var. Writes are on by default.
- **Environment.** Requests go to production `connect.squareup.com` unless `SANDBOX=true`. Setting both `SANDBOX` and `PRODUCTION` throws ([server.ts#L78-L90](https://github.com/square/square-mcp-server/blob/b276734fe2f1e6d4990fd99c2189c5d8d280a8b8/server.ts#L78-L90)). The default is **production**.
- **Forced discovery.** The tool descriptions tell the model to call `get_service_info` and then `get_type_info` before `make_api_request`. This guides the model and is not enforced.
- No annotations. With a single `make_api_request` tool covering both reads and writes, a client can't approve by tool name. The same problem appears with Stripe's `stripe_api_write`.

## Notes

- The README says "Most people should use the hosted server". This repo is described as a self-hosted starting point generated from Square's API spec, so the hosted server's behaviour may differ.
