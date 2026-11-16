# Linear MCP Server (official, hosted)

| Field | Value |
|---|---|
| Vendor | Linear; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.linear.app/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.linear.app/mcp (read-only variant: https://mcp.linear.app/mcp/readonly; SSE `/sse` deprecated) |
| Uses elicitation | no mention |
| Mechanism | unknown (docs don't say) |
| Evidence type | docs only |

Main source: [Linear MCP docs](https://linear.app/docs/mcp).

## Elicitation usages

The docs don't describe the server asking the user anything during a tool call.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting a client | n/a (client-run OAuth, not described as elicitation) | auth-oauth | Interactive setup uses "OAuth 2.1 with dynamic client registration". A bearer OAuth token or a Linear API key can be used instead | docs don't say | [docs](https://linear.app/docs/mcp) |
| Assigning a user by partial name | n/a (tool result, not a user prompt) | disambiguate | Nothing is asked. "a name that matches more than one user returns the possible matches" to the caller | n/a | [changelog 2026-11-04](https://linear.app/changelog/2026-11-04-mobile-diffs) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Read-only endpoint and scope.** `/mcp/readonly` "only ever exposes read tools". A client that asks only for the `read` OAuth scope is "granted read-only access", and its token "can't reach write APIs". An API key with only the Read permission has the same effect ([docs](https://linear.app/docs/mcp)).
- **Confirmation lives in prompts, not in the server.** The docs' example prompts tell the agent to show its planned updates "before applying any changes" and to show the proposed structure "before creating anything" ([docs](https://linear.app/docs/mcp)). These are instructions to the model, and the docs describe nothing that enforces them.
- **Server instructions.** "The Linear MCP server now gives clients default instructions on how to use its tools effectively" ([changelog 2026-11-04](https://linear.app/changelog/2026-11-04-mobile-diffs)). Their content isn't published on the pages reviewed.
- **Destructive operations.** Docs don't say. The docs describe tools for "finding, creating, and updating objects in Linear like issues, projects, and comments" and never mention a delete tool ([docs](https://linear.app/docs/mcp)). The changelog entries reviewed list create, edit and manage additions only ([2026-02-05](https://linear.app/changelog/2026-02-05-linear-mcp-for-product-management)).
- **Workspace selection.** Each workspace needs its own auth context, because "reconnecting alone does not switch the workspace". The docs suggest separate config directories through `MCP_REMOTE_CONFIG_DIR` ([docs](https://linear.app/docs/mcp)). The server doesn't ask which workspace.
- **Admin-managed sign-in.** Okta SAML customers can enable "MCP enterprise managed authentication". Claude-issued auth (beta) is configured under "Workspace settings → Security", requires "admin access in both Claude and Linear", and lets Claude admins choose "who gets the connector". "Members retain their existing Linear permissions" ([docs](https://linear.app/docs/mcp)).

## Notes

- Linear handles an ambiguous user name by returning the candidates in the tool result. The model or the user then has to pick one. The server does not prompt for the choice.
