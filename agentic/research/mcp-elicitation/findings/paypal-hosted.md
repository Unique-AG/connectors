# PayPal MCP (hosted / remote)

| Field | Value |
|---|---|
| Vendor | PayPal; official |
| Category | payments |
| Tier | 2 |
| Source | closed (https://mcp.paypal.com) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.paypal.com (production), https://mcp.sandbox.paypal.com (sandbox); `/sse` or `/http` |
| Uses elicitation | unknown (docs don't say) |
| Mechanism | n/a (none documented) |
| Evidence type | docs only |

All sources read 2026-11-16. The open-code agent toolkit is in `paypal.md`.

## Elicitation usages

None documented. The docs don't describe any confirmation, approval or question to the user for any tool, including refunds, disputes or captures.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting to the remote server | url (browser sign-in, at connect time, not during a tool call) | auth-oauth | "The MCP client sends you to the PayPal login page." The user logs in, then "Authorize[s] the client to work with the MCP server." | docs don't say | [developer.paypal.com/ai-tools/mcp-server](https://developer.paypal.com/ai-tools/mcp-server) |

Write and money-moving tools listed in the agent tools reference, all without any confirmation note ([developer.paypal.com/ai-tools/agent-tools](https://developer.paypal.com/ai-tools/agent-tools)):

- `create_refund`: "Process a refund for a captured payment." If `amount` is omitted, "a refund is for the full amount of the purchase."
- `accept_dispute_claim`: "Accept a dispute claim, resolving it in favor of the buyer."
- `pay_order`: "Capture payment for an authorized order."
- `cancel_sent_invoice`, `cancel_subscription`, `send_invoice`, `send_invoice_reminder`, `update_subscription`, `update_shipment_tracking`.
- Remote-only commerce tools (gift cards; need the header `x-feature-flags: commerce:true`): `search_product`, `create_cart`, and `checkout_cart`, which "handles payment processing, transaction validation, and purchase confirmation". The docs don't say whether "purchase confirmation" involves the user.

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- Sandbox and production are separate endpoints: "When you develop and test, use the sandbox environment variable. For a live site, use production." ([mcp-server](https://developer.paypal.com/ai-tools/mcp-server))
- Sign-in: PayPal login and consent in the browser, or "your PayPal client credentials" ([mcp-server](https://developer.paypal.com/ai-tools/mcp-server)). Scopes and admin controls: docs don't say.
- Read-only mode, tool allowlists, annotations: docs don't say.
- Disclaimer: the server provides "AI-generated content that may be inaccurate or incomplete" and "Users are responsible for independently verifying any information before relying on it." ([blog](https://developer.paypal.com/community/blog/paypal-mcp-agenttoolkit/))
- PayPal's REST refund guide (not MCP-specific) recommends that integrators "Implement refund approval workflow" ([developer.paypal.com/checkout/refund-payment](https://developer.paypal.com/checkout/refund-payment)). The docs don't say whether the MCP server does this.

## Notes

- The quickstart's invoice example says only that "The user supplies the necessary information, as the MCP client indicates", which means the client prompts for it, not the server ([mcp-server](https://developer.paypal.com/ai-tools/mcp-server)).
- The docs disagree on the remote tool set. The quickstart says "The complete catalog of tools is available in both local and remote MCP server" ([mcp-server](https://developer.paypal.com/ai-tools/mcp-server)). The limited-release agents page says "Remote MCP server offers the following 2 tools" ([developer.paypal.com/limited-release/agents](https://developer.paypal.com/limited-release/agents/)). A blog post says refund tools are available in "remote MCP-hosted server configurations" ([blog](https://developer.paypal.com/community/blog/paypal-mcp-agenttoolkit/)).
- A PayPal post mentions "maintaining oversight through human-in-the-loop governance" as a general principle of MCP, not as behaviour of this server ([blog](https://developer.paypal.com/community/blog/trust-transperancy-security-payments/)).
- Disambiguation: docs don't say.
