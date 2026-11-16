# Quartr Pro MCP

| Field | Value |
|---|---|
| Vendor | Quartr; official |
| Category | market-data |
| Tier | 2 |
| Source | closed (https://mcp.quartr.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.quartr.com/mcp (Streamable HTTP, stateless, OAuth 2.1 + PKCE) |
| Uses elicitation | unknown (docs don't mention it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16: overview [mcp.quartr.com/docs](https://mcp.quartr.com/docs), tool reference [mcp.quartr.com/docs/tools](https://mcp.quartr.com/docs/tools) (also served as [tools.md](https://mcp.quartr.com/docs/tools.md)).

## Elicitation usages

None documented. The docs describe no step where a tool call pauses to ask the user something. They do not use the words "elicitation", "confirm" (except once, telling the model to check a reporting period), or "ask the user".

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| First connection (not a tool call) | browser OAuth, outside MCP | auth-oauth | Client "open[s] a browser where you approve access and sign in with your Quartr account". The consent screen has a "Read-only access" tick box | docs don't say | [docs#authentication](https://mcp.quartr.com/docs#authentication) |

## Fallback without client elicitation support

Docs don't say. Nothing documented depends on elicitation.

## Other human-in-the-loop mechanisms

- **Not read-only.** 48 tools: 27 labelled "Read-only", 11 "Write", 10 "Destructive" ([tools](https://mcp.quartr.com/docs/tools)). Write and destructive tools act on the user's own Quartr objects: watchlists, keyword alerts, saved items and folders, workspaces, saved search filters. Examples: `delete_watchlist`, `remove_from_watchlist`, `delete_keyword`, `update_keyword` ("Replaces the company scope, event types, and document types"), `delete_workspace`, `write_workspace`. No documented confirmation step on any of them.
- **Read-only scope chosen at sign-in.** "To connect without write access, tick Read-only access on the consent screen, or have your client request the `mcp:read` scope. Read-only connections only see the tools marked Read-only, so the AI can't create, change, or delete watchlists, keywords, saved items, workspaces, or search filters." Full access uses scope `mcp:tools` ([docs#read-only-access](https://mcp.quartr.com/docs#read-only-access)). The choice is made once per connection, not per call.
- **Undo instead of a prompt on one destructive tool.** `write_workspace`: "A snapshot of the prior state is automatically taken so the user can revert via the workspace's version history." Its `mode` parameter says "Prefer `append` unless the user asked for a full rewrite." That is guidance to the model, not a question to the user ([tools#workspaces](https://mcp.quartr.com/docs/tools#workspaces)).
- **Labels.** The docs show "Read-only" / "Write" / "Destructive" per tool. They don't say whether these are sent as MCP `readOnlyHint` / `destructiveHint` annotations.
- **Entitlement.** "A Quartr Pro subscription is required. Student plans are not eligible." `get_current_user` is "Available regardless of subscription status" and returns the user's subscription type and status. What other tools do for a user without a subscription: docs don't say ([docs](https://mcp.quartr.com/docs), [tools#users](https://mcp.quartr.com/docs/tools#users)).
- **Rate limits, no cost prompt.** Per tool 20–100 requests/minute. All tools combined 100/minute, 2,250/hour, 8,500/day, per user. Over a combined limit: HTTP 429 with `Retry-After`. Over a per-tool limit: an error result with `error: "rate_limited"` and `retryAfterSeconds`. "Rejected requests do not count toward the hourly or daily limits" ([docs#rate-limits](https://mcp.quartr.com/docs#rate-limits)). The user is not asked before a call uses quota.
- **Disambiguation is left to the model.** `search_companies` takes a name, ticker, CIQ ID, FIGI or ISIN and returns paginated `matches` (default 5 per page). Other tools take numeric company IDs. The docs don't say whether the server or the model should ask the user when several companies match.

## Notes

- This is the only server in this batch whose public docs list write and destructive tools. Its safeguard is a connection-level read-only scope chosen on the OAuth consent screen, not a prompt at call time.
- The docs say the MCP server "is for individual subscribers doing their own research workflows". Products built on Quartr data should use the Quartr Public API instead.
- In Microsoft 365 Copilot, both the agent and the connector "ask you to sign in with your Quartr account on first use" and are "controlled by your Microsoft 365 admin" ([docs#connect-a-client](https://mcp.quartr.com/docs#connect-a-client)).
- Open question: what the tools return for a signed-in user whose subscription has lapsed.
