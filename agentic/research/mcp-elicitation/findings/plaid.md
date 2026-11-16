# Plaid Dashboard MCP

| Field | Value |
|---|---|
| Vendor | Plaid; official |
| Category | banking (developer diagnostics) |
| Tier | 2 |
| Source | closed (https://api.dashboard.plaid.com/mcp/) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://api.dashboard.plaid.com/mcp/ (Streamable HTTP) |
| Uses elicitation | unknown (docs don't say) |
| Mechanism | n/a (none documented) |
| Evidence type | docs only |

All sources read 2026-11-16.

## Elicitation usages

None documented. Every documented tool is diagnostic or a read, so there is no destructive or money-moving operation to confirm.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting from a hosted assistant (Claude) | url (sign-in at connect time) | auth-oauth | "The user will be prompted to log in to their Plaid Dashboard account." | docs don't say | [plaid.com/blog/plaid-mcp-ai-assistant-claude](https://plaid.com/blog/plaid-mcp-ai-assistant-claude/) |

Documented tools and their purposes ([plaid.com/docs/resources/mcp](https://plaid.com/docs/resources/mcp/)):
- `plaid_debug_item`: "Diagnose a Plaid Item using related metadata."
- `plaid_get_link_analytics`: "Retrieve Link funnel, conversion, and error metrics."
- `plaid_get_tools_introduction`: "Get usage guidance for Dashboard MCP tools."
- `plaid_get_usages`: "Retrieve product usage metrics and API request volumes."
- `plaid_list_teams`: "List teams available to the OAuth token."

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- Programmatic sign-in: an OAuth token from `/oauth/token` with `client_credentials` and the scope `mcp:dashboard`. "Access tokens for the MCP server expire after 15 minutes", and a refresh token is issued. ([docs](https://plaid.com/docs/resources/mcp/))
- Permissions: access is limited "to what they have permission to access in Plaid". An organization owner "can add the Plaid MCP Server for everyone" in Claude, and each user then connects separately. ([blog](https://plaid.com/blog/plaid-mcp-ai-assistant-claude/))
- Production only: "The Dashboard MCP server works with Production data only." The team "must be approved for Production access with at least one Plaid product". ([docs](https://plaid.com/docs/resources/mcp/))
- Data boundary: "Claude does not have access to consumer financial data." ([blog](https://plaid.com/blog/plaid-mcp-ai-assistant-claude/))
- Write tools, read-only flag, confirmation, admin controls: docs don't say.

## Notes

- Disambiguation: when a token reaches several teams, `plaid_list_teams` lists them, and the docs' example passes a `team_id` to `plaid_get_link_analytics`. The docs don't say whether `team_id` is required or whether the server asks the user to choose ([docs](https://plaid.com/docs/resources/mcp/)).
- The docs' OpenAI Responses API example sets `"require_approval": "never"`, which turns off client-side approval for these tools ([docs](https://plaid.com/docs/resources/mcp/)).
- Stability: "Breaking changes may occur, and Plaid currently provides limited support." ([docs](https://plaid.com/docs/resources/mcp/))
- Plaid also ships a local MCP server in its AI coding toolkit (Sandbox tokens, mock data, webhook simulation, docs search). It "runs as a subprocess of an MCP client" and is not a hosted server, so it is out of scope here ([docs](https://plaid.com/docs/resources/mcp/)).
