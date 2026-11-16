# Asana MCP Server (V2, official, hosted)

| Field | Value |
|---|---|
| Vendor | Asana; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.asana.com/v2/mcp) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.asana.com/v2/mcp (the beta server was "deprecated and will be shut down on 05/11/2026") |
| Uses elicitation | no mention |
| Mechanism | n/a as documented. Access changes use a call-twice confirmation argument, and drafts use interactive preview tools in clients that support them |
| Evidence type | docs only |

Main sources: [MCP Tools Reference](https://developers.asana.com/docs/mcp-tools-reference) and [Using Asana's MCP Server](https://developers.asana.com/docs/using-asanas-mcp-server).

## Elicitation usages

The docs don't mention elicitation. Two documented flows ask the user something without it.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `update_project` changing access (adding members, making the project public, changing default access) | n/a (confirmation argument; the tool is called twice) | consent-data-sharing | Whether to apply the access change. Such changes require "explicit user confirmation. For those access changes, call without confirmation first to review the effects, then retry with confirmation after approval." | docs don't say. Without confirmation, the first call is described only as a review step | [tools reference](https://developers.asana.com/docs/mcp-tools-reference) |
| `create_task_preview`, `create_project_preview` | n/a (interactive app UI) | other (review a draft before it is created) | The user sees a drafted task, or a project plan with sections and tasks, to review before it is created. "Availability depends on whether the client supports interactive apps." | docs don't say | [tools reference](https://developers.asana.com/docs/mcp-tools-reference) |
| Connecting a client | n/a (client-run OAuth, not described as elicitation) | auth-oauth | "you'll be prompted to authorize the application to access your Asana data". The user also picks one workspace: "When you authorize an MCP session, you select a specific workspace." | docs don't say | [using the server](https://developers.asana.com/docs/using-asanas-mcp-server), [tools reference](https://developers.asana.com/docs/mcp-tools-reference) |

## Fallback without client elicitation support

Not applicable as documented. Clients without interactive apps "can use the standard read and write tools". `create_tasks` and `create_project` create "immediately", and the docs say to use a preview tool "when the user asks to review before creating" ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)).

## Other human-in-the-loop mechanisms

- **Deletes have no documented confirmation.** `delete_task` "Deletes a task and any subtasks that are not also members of another project. Use care when deleting tasks." `delete_record` "Permanently deletes a record. This cannot be undone through this tool." No project delete tool is listed ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)).
- **No scopes.** "MCP apps in Asana do not use permission scopes." Authorization grants every tool, but tools can't reach data the user can't already see ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)).
- **Workspace scoping instead of asking.** "Tokens are workspace-scoped." Working across workspaces needs separate sessions ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)).
- **Server defaults instead of disambiguation.** For `create_project`: "If no team is provided, the server chooses a default team." `search_objects` "Finds objects by name when you don't know the GID" ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)). The docs describe no prompt to choose between matches.
- **Admin controls.** Enterprise+ and Legacy Enterprise admins "can use Asana's app management to allow or block Asana MCP clients", configured "per-client". Other tiers go through support ([using the server](https://developers.asana.com/docs/using-asanas-mcp-server)).
- **MCP-only tokens.** "Tokens issued for MCP apps are valid only for the MCP server" ([tools reference](https://developers.asana.com/docs/mcp-tools-reference)).

## Notes

- Asana documents user review in two ways. Access changes use a confirmation argument and two calls. New tasks and projects use preview tools rendered as an interactive UI, available only in clients that support interactive apps. Neither is described as MCP elicitation.
