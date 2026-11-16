# Slack MCP Server (official, hosted)

| Field | Value |
|---|---|
| Vendor | Slack (Salesforce); official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.slack.com/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.slack.com/mcp |
| Uses elicitation | no mention |
| Mechanism | unknown (docs don't say) |
| Evidence type | docs only |

Main source: [Slack MCP server overview](https://docs.slack.dev/ai/slack-mcp-server/), also served as [markdown](https://docs.slack.dev/ai/slack-mcp-server.md).

## Elicitation usages

The docs don't describe the server asking the user anything during a tool call. The only documented user prompt is the OAuth consent when a client connects. That prompt comes from the client's OAuth flow, and the docs don't call it elicitation.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting an MCP client | n/a (client-run OAuth, not described as elicitation) | auth-oauth | The user approves the client app's access to their Slack: "Users go through OAuth consent and authorize the app." The client starts the request "following standard MCP metadata discovery files" | docs don't say | [overview](https://docs.slack.dev/ai/slack-mcp-server/) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Tool surface.** The documented tools search, read, send and schedule messages, draft messages, create channels and DMs, add reactions, create, update and read canvases, read profiles, list members and channels, upload files, and create, read and update lists ([overview](https://docs.slack.dev/ai/slack-mcp-server.md)). The [2026-05-13 changelog](https://docs.slack.dev/changelog/2026/05/13/new-mcp-tools) added file reading and an add-reaction tool that acts "on behalf of the authenticated user".
- **No delete or edit-message tools are listed.** The overview names no tool that deletes or edits a message, and no tool that deletes a canvas, channel, file or list. The docs don't say whether this is deliberate.
- **Drafts.** One capability is "Draft messages — draft, format, and preview messages directly within AI clients" ([overview](https://docs.slack.dev/ai/slack-mcp-server.md)). The docs don't say whether a draft has to be reviewed before a separate send. "Send message" is its own tool with scope `chat:write`.
- **Per-tool OAuth scopes.** Each tool lists the scopes it needs, for example `chat:write` to send, `files:write` to upload and `search:read.public` to search ([overview](https://docs.slack.dev/ai/slack-mcp-server/)).
- **Admin approval.** "Workspace admins can approve and manage all MCP client integrations." Clients go through the "standard Slack app approval process" ([overview](https://docs.slack.dev/ai/slack-mcp-server/)).
- **Which apps may connect.** "Only directory-published apps or internal apps may use MCP", and "unlisted apps are prohibited from using MCP" ([overview](https://docs.slack.dev/ai/slack-mcp-server/)).
- **Audit.** "Audit MCP activity with the associated" audit logs ([overview](https://docs.slack.dev/ai/slack-mcp-server/), [audit log actions](https://docs.slack.dev/reference/audit-logs-api/methods-actions-reference.md#mcp-server)).
- **Disambiguation.** Docs don't say. The only workspace-related statement is that "List user channels" is "filterable by type ..., name prefix, and workspace" ([overview](https://docs.slack.dev/ai/slack-mcp-server/)). Nothing describes the server asking which workspace, channel or user is meant.

## Notes

- The Slack blog post [How Slack Keeps MCP Secure](https://slack.com/blog/news/slackbot-mcp-security) says "Write and delete tools will require explicit, per-action user confirmation before Slackbot proceeds." That sentence is about Slackbot acting as an MCP **client** that calls external servers. It does not describe the Slack MCP server used by third-party AI clients.
- Third-party guides say clients show a confirmation dialog before a message is posted. Those dialogs belong to the clients, and Slack's own server docs don't mention them.
