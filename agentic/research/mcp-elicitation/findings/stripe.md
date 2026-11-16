# Stripe MCP (hosted `mcp.stripe.com`, plus the retired `@stripe/mcp` proxy and agent toolkit)

| Field | Value |
|---|---|
| Vendor | Stripe; official |
| Category | payments |
| Tier | 1 |
| Source | closed (https://mcp.stripe.com). Open parts: https://github.com/stripe/ai @ 9d6c33b (`main`, plugins and skills only) and @ a3196df (`ai-packages-final`, the deprecated local proxy and agent toolkit) |
| Language / SDK | Hosted server: unknown. Proxy: TypeScript, `@modelcontextprotocol/sdk` ^1.17.1. Python toolkit: `mcp>=1.0.0` |
| Hosted endpoint | https://mcp.stripe.com (OAuth or agent API key) |
| Uses elicitation | unknown (hosted is closed); no in the open code |
| Mechanism | n/a in the open code. Hosted: out-of-band "Human confirmation" approval URL; the protocol carrier is not confirmed |
| Evidence type | code + docs only |

## Elicitation usages

The open code has none. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` on `main` or `ai-packages-final`.

The hosted server has a documented approval flow that does the job of URL-mode elicitation. We could not confirm whether it travels as `elicitation/create` (mode `url`), as a `URLElicitationRequiredError`, or as plain text in the tool result.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `stripe_api_write` → create refund; `send_money`, `transfer_money`, `convert_currency` (Treasury); plus account-specific approval rules | url-like, out of band (carrier unconfirmed) | confirm-cost | "click the URL provided by your agent and review the details of the request" in the Stripe Dashboard, then **Approve** | If not approved within 24 h the request expires. After approval Stripe gives the agent an approval token, but the user must tell the agent to retry; the retry needs no further confirmation | [docs.stripe.com/mcp, "Confirm actions by agents acting on your behalf"](https://docs.stripe.com/mcp) (read 2026-11-16) |

The docs say confirmation is tied to the API action, not the tool name. `stripe_api_write` covers many actions, and only some of them need confirmation.

## Fallback without client elicitation support

- The retired local proxy (`@stripe/mcp`) is a transparent stdio↔Streamable-HTTP pipe to `https://mcp.stripe.com`. It forwards every JSON-RPC message both ways ([index.ts#L46](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/modelcontextprotocol/src/index.ts#L46), [#L69](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/modelcontextprotocol/src/index.ts#L69)). If the hosted server sent an elicitation request, it would reach the stdio client unchanged. Capability negotiation is end to end.
- The retired agent toolkit connects to the hosted server as an MCP client with `capabilities: {}` and no elicitation handler ([mcp-client.ts#L69-L77](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/typescript/src/shared/mcp-client.ts#L69-L77), Python `ClientSession(read_stream, write_stream)` with no `elicitation_callback` at [mcp_client.py#L106](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/python/stripe_agent_toolkit/shared/mcp_client.py#L106)). Toolkit-driven agents therefore never support elicitation. The docs' wording ("click the URL provided by your agent", "tell the agent to retry") suggests the approval URL comes back in the tool result, so it works with any client. That is an inference, not verified.

## Other human-in-the-loop mechanisms

- **Scoped credentials instead of per-call prompts.** At OAuth consent you pick live-mode accounts and sandboxes, each with its own permissions. Autonomous clients use *agent API keys* with least privilege. From December 2026 the hosted server rejects full secret keys and untagged restricted keys with a `401` and an OAuth discovery challenge (docs). The old proxy already told users that "Tool permissions are now controlled by your Restricted API Key (RAK)" ([cli.ts#L21](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/modelcontextprotocol/src/cli.ts#L21)) and warned on `sk_*` keys ([cli.ts#L59](https://github.com/stripe/ai/blob/a3196df9925589ec7dd96c90692d13ea1c453cae/tools/modelcontextprotocol/src/cli.ts#L59)).
- **Org-level switch.** Admins can turn MCP access on or off for the team, separately for live mode and sandboxes. Admins can also revoke OAuth sessions (docs).
- **Client tool approval.** The docs tell users to "Turn on your MCP client's tool-approval setting so you can review tool calls before they run".
- **Skill-level prompting.** The `stripe-pay` skill tells the agent to "show the exact `stripe pay ...` command you plan to run and get confirmation" and not to pass `-y`/`--yes` until the user confirms ([SKILL.md#L35-L37](https://github.com/stripe/ai/blob/9d6c33b367f2c823cb3c88d991cafdd3402ceeb0/providers/claude/plugin/skills/stripe-pay/SKILL.md#L35-L37)). That is CLI, not MCP.
- **Atlas** (`atlas_company_formation`): the agent only prepares the application. Paying, signing and submitting happen in the Dashboard (docs).

## Notes

- All the open-source MCP code is deprecated. `main` now ships only plugins and skills that point at `https://mcp.stripe.com`. The hosted server is the real product, and its source is not public.
- Stripe's "Human confirmation" is the clearest production example in this batch of a URL-approval-plus-retry pattern for money movement. It matches what URL-mode elicitation was designed for, but it apparently relies on the user to re-prompt the agent rather than on the protocol. A live probe with an elicitation-capable client against a sandbox refund would settle which carrier it uses.
