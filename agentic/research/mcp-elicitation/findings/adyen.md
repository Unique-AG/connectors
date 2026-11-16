# Adyen MCP Server

| Field | Value |
|---|---|
| Vendor | Adyen; official |
| Category | payments |
| Tier | 2 |
| Source | open (https://github.com/Adyen/adyen-mcp @ 5a54794) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` ^1.0.4 (package-lock resolves 1.32.0) |
| Hosted endpoint | none (stdio only) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state`. Tools go through `server.registerTool` with `description`, `annotations` and `inputSchema`. The handler ignores `extra` and returns `JSON.stringify(result)` ([index.ts#L38-L56](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/index.ts#L38-L56)). The resolved SDK supports elicitation, but the server doesn't use it.

## Fallback without client elicitation support

Not applicable. `refund_payment`, `cancel_payment`, terminal actions and payment-link updates all run immediately.

## Other human-in-the-loop mechanisms

- **Annotations everywhere.** Each tool uses one of two helpers. `readOnly(title)` sets `readOnlyHint: true, destructiveHint: false, idempotentHint: true`. `writes(title, {destructive, idempotent})` sets `readOnlyHint: false` and an explicit `destructiveHint` ([annotations.ts](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/tools/annotations.ts)). Refund and cancel are `destructive: true` ([modifications/index.ts#L85-L93](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/tools/checkout/modifications/index.ts#L85-L93)). Creating a payment link or session is `destructive: false`. Of the payments servers in this batch, Adyen annotates most consistently.
- **TEST by default, LIVE takes extra setup.** `--env` defaults to `TEST`. `LIVE` requires a `--livePrefix`, otherwise startup throws. It also warns if the API key came from argv instead of `ADYEN_API_KEY` ([configurations.ts#L33-L36](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/configurations/configurations.ts#L33-L36), [#L59-L65](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/configurations/configurations.ts#L59-L65), [#L96-L107](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/configurations/configurations.ts#L96-L107)).
- **Tool allowlist.** `--tools a,b,c` exposes only the named tools. Unknown names are logged, and an empty result aborts startup ([tools.ts, `getActiveTools`](https://github.com/Adyen/adyen-mcp/blob/5a547944019d8461fff021367e31befd8efcb9a5/typescript/src/tools/tools.ts)). The default is all tools.
- **API key scope.** Adyen API credentials carry roles, so which tools actually work depends on the key's roles.

## Notes

- The tool surface is mostly read-only. Money movement is limited to refund/cancel of an existing PSP reference and creating payment links or sessions that a shopper must still complete. The server never pulls funds by itself.
