# PayPal MCP (`@paypal/mcp` + `@paypal/agent-toolkit`)

| Field | Value |
|---|---|
| Vendor | PayPal; official |
| Category | payments |
| Tier | 1 |
| Source | open (https://github.com/paypal/agent-toolkit @ a3aa963, holds the MCP server class; https://github.com/paypal/paypal-mcp-server @ 6b1ced2, the `@paypal/mcp` stdio CLI). The hosted server is closed |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` ^1.6.1 in both repos (no lockfile committed) |
| Hosted endpoint | https://mcp.paypal.com (`/sse`, `/http`; sandbox at `mcp.sandbox.paypal.com`), per PayPal docs; not reviewed |
| Uses elicitation | no (open code); unknown (hosted) |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` in either repo. The MCP server registers every tool with the legacy `this.tool(name, description, shape, handler)` overload. Handlers ignore the `extra` argument and just return `String(result)` ([toolkit.ts#L29-L48](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/modelcontextprotocol/toolkit.ts#L29-L48)).

## Fallback without client elicitation support

Not applicable. Every tool, including money-moving ones such as `pay_order` (capture), `create_refund`, `accept_dispute_claim` and `cancel_subscription`, runs immediately when called.

## Other human-in-the-loop mechanisms

- **Mandatory tool allowlist.** `@paypal/mcp` refuses to start without `--tools=` ([index.ts#L80](https://github.com/paypal/paypal-mcp-server/blob/6b1ced271959d5ea53857502dc6e5ddef0cbc126/src/index.ts#L80)), checked against a fixed `ACCEPTED_TOOLS` list of `product.action` entries ([#L24](https://github.com/paypal/paypal-mcp-server/blob/6b1ced271959d5ea53857502dc6e5ddef0cbc126/src/index.ts#L24)). `--tools=all` turns on everything. The toolkit drops tools whose `actions` are not enabled ([configuration.ts#L20](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/shared/configuration.ts#L20)).
- **Sandbox by default, in the CLI only.** `@paypal/mcp` uses sandbox unless `PAYPAL_ENVIRONMENT`/`--paypal-environment` is `production` ([index.ts#L106-L112](https://github.com/paypal/paypal-mcp-server/blob/6b1ced271959d5ea53857502dc6e5ddef0cbc126/src/index.ts#L106-L112)). The underlying `PayPalAPI` class defaults the other way, to **production**, when `context.sandbox` is unset ([api.ts#L62-L64](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/shared/api.ts#L62-L64)), although the toolkit README says the default is sandbox. Anyone who embeds `PayPalAgentToolkit` directly lands on live by default.
- **Buyer approval by PayPal's own flow, not MCP.** `create_order` returns an approval link that the payer opens at PayPal. `pay_order` then captures the order. The tool descriptions do not tell the model to wait for or check that approval ([prompts.ts#L281-L297](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/shared/prompts.ts#L281-L297)). The Python prompt does say "Use this tool after the user has approved the PayPal order".
- **Prompt-level disambiguation only.** The refund prompt says "If multiple captures exist for an order, request clarification on which specific capture to refund" ([prompts.ts#L362-L368](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/shared/prompts.ts#L362-L368)). This is a natural `disambiguate` elicitation, delegated to the model instead.
- No tool annotations (`readOnlyHint`/`destructiveHint`), no confirm or dry-run arguments.

## Notes

- `agent-toolkit` also has a `PayPalMCPToolkit` tagged `source: 'Remote MCP'` that only hands out filtered tools and the API service ([mcpToolkit.ts](https://github.com/paypal/agent-toolkit/blob/a3aa963960caf32912691a759879a8ce7a6018b2/typescript/src/modelcontextprotocol/mcpToolkit.ts)). The hosted server probably wraps it, so the hosted tool set is likely to behave the same way (no elicitation). We did not verify this.
- `paypal-mcp-server` pins `@paypal/agent-toolkit` to `latest`, so the published CLI's behaviour follows whatever toolkit version npm resolves at install time.
