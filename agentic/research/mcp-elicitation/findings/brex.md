# Brex MCP (hosted)

| Field | Value |
|---|---|
| Vendor | Brex; official (beta) |
| Category | banking (corporate cards, spend management) |
| Tier | 2 |
| Source | closed (https://api.brex.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://api.brex.com/mcp (OAuth with DCR, or Brex API token) |
| Uses elicitation | unknown (docs don't say) |
| Mechanism | n/a (none documented) |
| Evidence type | docs only |

All sources read 2026-11-16.

## Elicitation usages

None documented during tool calls. The developer docs say approvals and card management are not available over MCP, and the documented write tools only edit expense details.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| First connection | url (browser sign-in at connect time) | auth-oauth | Clients "automatically initiate a browser-based authorization flow when you first connect". The user signs in with their Brex email or SSO, then "Approve[s] the permission request." | docs don't say | [developer.brex.com/docs/mcp](https://developer.brex.com/docs/mcp), [brex.com/support/using-brex-in-ai-apps](https://www.brex.com/support/using-brex-in-ai-apps) |

Write tools in the developer docs' tool table: `update_expense_memo` (bulk), `upload_card_expense_receipt_from_urls`, `replace_attendees_for_card_expense`, `assign_limit_for_card_expenses`, `start_expense_download`, `submit_feedback`. None has a confirmation note. ([developer.brex.com/docs/mcp](https://developer.brex.com/docs/mcp))

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- Client-side approval is recommended: "**Enable human confirmation.** Configure your AI assistant to require approval before executing actions." ([developer.brex.com/docs/mcp](https://developer.brex.com/docs/mcp))
- Operations left out on purpose: "Actions like approvals and card management are not yet available via MCP." "Brex does not and will not expose raw card numbers (PANs), CVVs, or expiration dates over MCP." ([developer.brex.com/docs/mcp](https://developer.brex.com/docs/mcp)) The support article sends users to the dashboard or mobile app to "create reimbursements, approve or reject expenses, or modify your team's transactions". ([support](https://www.brex.com/support/using-brex-in-ai-apps))
- Scope gating: each tool requires a Brex capability (the table's "Access" column), and "you only see and modify what you're authorized to." With OAuth, "the MCP server requests exactly the permissions its tools require, and you approve them in the authorization prompt." With an API token, "If a scope is omitted (for example, cards read), the corresponding tools will be unavailable." ([developer docs](https://developer.brex.com/docs/mcp), [support](https://www.brex.com/support/using-brex-in-ai-apps))
- Own data only for writes: users can modify "memos, receipts, attendees, and spend limits for your own transactions only." ([support](https://www.brex.com/support/using-brex-in-ai-apps))
- Admin controls: an account or card admin must accept the Developer API agreement and turn on the beta ("Brex in AI assistants" / "Brex MCP access"). In ChatGPT, the admin can "configure actions that should be available to your organization". Users can revoke sessions under Settings → Personal settings → Connected integrations. ([developer docs](https://developer.brex.com/docs/mcp), [support](https://www.brex.com/support/using-brex-in-ai-apps))
- Audit: "All actions taken via the MCP server are recorded as the MCP client on behalf of the authenticated user when using OAuth." ([support](https://www.brex.com/support/using-brex-in-ai-apps))
- Sandbox: docs don't say.

## Notes

- The two official pages disagree about card writes. The developer docs list only read card tools and say card management is "not yet available via MCP". The support article lists card write actions for card admins in Claude and ChatGPT ("Create/update a purchasing card (admin only)", "Cancel a card", "Lock/unlock a card", "Transfer a card"), with "Card admins can also manage cards, including creating, updating, shipping, locking, and canceling." Neither page describes a confirmation step for these actions.
- Disambiguation (for example, which card or account): docs don't say.
