# Stripe MCP (hosted, `mcp.stripe.com`)

| Field | Value |
|---|---|
| Vendor | Stripe; official |
| Category | payments |
| Tier | 1 |
| Source | closed (https://mcp.stripe.com) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.stripe.com (OAuth, or an agent API key as bearer token) |
| Uses elicitation | unknown. The docs describe an out-of-band approval step that does the job; they don't say whether it is carried by MCP elicitation |
| Mechanism | docs don't say. Functionally: an approval URL the user opens in the Stripe Dashboard |
| Evidence type | docs only |

All sources read 2026-11-16. The open-code side (retired proxy, agent toolkit) is in `stripe.md`.

## Elicitation usages

Two documented flows, depending on how the agent signed in.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| OAuth session (agent acting as the signed-in user): `stripe_api_write` → Create refund; Treasury tools `send_money`, `transfer_money`, `convert_currency`; plus "Account-specific approval rules" | url-like, out of band | confirm-cost | The user is asked to "click the URL provided by your agent and review the details of the request" in the Dashboard, then click **Approve**. The screenshot is captioned "Confirm a refund request". | "If you don't approve the action within 24 hours, it expires." After approval "Stripe provides the agent with an approval token, but you need to tell the agent to retry the operation, which doesn't require human confirmation." Deny: docs don't say | [docs.stripe.com/mcp#confirm-actions](https://docs.stripe.com/mcp) |
| Agent-tagged API key: default approval rules for refund created, subscription canceled, outbound payment, outbound transfer, payout, currency conversion; admins can add rules for more actions | out of band, to a different person | confirm-cost / confirm-destructive (two-party) | A "designated reviewer" approves or denies in the Dashboard (Settings → Approvals → Requests) or the mobile app. Individually assigned reviewers get email and push notifications. "A user can't approve their own request." | The agent's call gets an `approval_required` error and Stripe "automatically submits an approval request". "Approved actions are completed automatically; denied actions are discarded with no changes made." Unreviewed requests expire after 14 days | [docs.stripe.com/account/approvals](https://docs.stripe.com/account/approvals), [docs.stripe.com/keys#agent-keys](https://docs.stripe.com/keys) |

Operations carrying the "Human confirmation" badge on the MCP page: Create refund (via `stripe_api_write`), `convert_currency` ("Converts funds between currencies within a Treasury account"), `send_money` ("Sends money from a Treasury account to a recipient"), `transfer_money` ("Transfers money between supported Stripe balances"). `setup_recipient` has no badge. ([docs.stripe.com/mcp#tools](https://docs.stripe.com/mcp))

What the agent sees:
- OAuth flow: a URL to pass to the user, then an approval token after the user approves. The docs don't say how the URL or token is delivered (tool result text, error, or elicitation).
- Agent-key flow: an `approval_required` error. The agent can attach a justification by updating the approval request (`POST /v2/core/approval_requests/{id}/update` with `reason`). Outcomes arrive as `v2.core.approval_request.*` events (approved, rejected, canceled, expired, succeeded, failed).

Confirmation is per action, not per tool: "creating a refund uses `stripe_api_write`, which also supports other actions that don't use this confirmation flow. Confirmation depends on the action, not only the tool name." ([docs.stripe.com/mcp](https://docs.stripe.com/mcp))

## Fallback without client elicitation support

Docs don't say. The OAuth flow is described in terms of a URL "provided by your agent" and the user telling the agent to retry, and the agent-key flow returns an error, so neither is described as depending on a client capability.

## Other human-in-the-loop mechanisms

- Client-side approval is recommended separately: "Turn on your MCP client's tool-approval setting so you can review tool calls before they run". Stripe's confirmation "is separate from your MCP client's tool-approval setting." ([docs.stripe.com/mcp#tools](https://docs.stripe.com/mcp))
- Sign-in: OAuth opens "Stripe's OAuth consent page", where the user can "grant access to one or more live mode accounts or sandboxes and set different permissions for each environment". Agent API keys are restricted keys with chosen permissions. From December 2026 the server stops accepting full-access secret keys and untagged restricted keys. ([docs.stripe.com/mcp#authenticate](https://docs.stripe.com/mcp))
- Read and write are separate tools: `stripe_api_read` ("any Stripe API `GET` method") and `stripe_api_write` (`POST`, `PATCH`, `PUT`, `DELETE`). The supported-method list includes destructive actions with no badge: void an invoice, mark an invoice uncollectible, cancel a subscription, delete a coupon. Payouts and transfers can only be listed or retrieved. ([docs.stripe.com/mcp#apis](https://docs.stripe.com/mcp))
- Approval rules (agent keys) can match on amount, actor or request rate, and can **Block** an action outright instead of requiring approval. ([docs.stripe.com/account/approvals](https://docs.stripe.com/account/approvals))
- Admin controls: an administrator can "enable or disable MCP access for your entire team", separately for live mode and sandboxes. Users and admins can revoke OAuth sessions. ([docs.stripe.com/mcp#manage-access](https://docs.stripe.com/mcp))
- Atlas: the agent prepares the company-formation application; "You review documents, pay, sign, and submit in the Dashboard." ([docs.stripe.com/mcp](https://docs.stripe.com/mcp))
- Connected accounts: chosen by a `Stripe-Account` header with an agent API key, not by asking the user. OAuth isn't supported for connected accounts.

## Notes

- Disambiguation (for example, asking which account): docs don't say. Account and environment are fixed at OAuth consent or by the key.
- The two pages disagree on what happens after approval. The MCP page says the user must tell the agent to retry with a token. The approvals page says approved actions "are completed automatically". They seem to describe two flows: self-confirmation for OAuth sessions, and two-party review for agent keys. The docs don't say which applies to an agent key used with the MCP server.
- Expiry also differs: 24 hours on the MCP page, 14 days on the approvals page.
- Payouts, outbound payments, outbound transfers and currency conversions can only be gated by approval rules when an agent-tagged key starts them ([approvals](https://docs.stripe.com/account/approvals)).
