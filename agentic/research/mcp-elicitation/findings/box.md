# Box MCP Server (remote, official)

| Field | Value |
|---|---|
| Vendor | Box; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.box.com) |
| Language / SDK | docs don't say |
| Hosted endpoint | https://mcp.box.com |
| Uses elicitation | no mention |
| Mechanism | unknown (docs don't say) |
| Evidence type | docs only |

Main sources: [remote server setup](https://developer.box.com/guides/box-mcp/remote), [available tools](https://developer.box.com/guides/box-mcp/tools), [Box MCP Server (support)](https://support.box.com/hc/en-us/articles/49221220102163-Box-MCP-Server) and [Manage Box MCP Server Tool Access](https://support.box.com/hc/en-us/articles/50837641642643-Manage-Box-MCP-Server-Tool-Access).

## Elicitation usages

The docs don't describe the server asking the user anything during a tool call.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting a client | n/a (client-run OAuth 2.0, not described as elicitation) | auth-oauth | The user goes through Box OAuth: authorization URL `https://account.box.com/api/oauth2/authorize`, scopes `root_readwrite`, `ai.readwrite` and `docgen.readwrite`. The docs don't describe what the user sees | docs don't say | [remote setup](https://developer.box.com/guides/box-mcp/remote) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **No delete tools.** None of the 54 tools in the published list deletes anything. The write tools copy, create, move, upload, update properties and metadata, create comments, change shared links and collaborations, change hubs, and run Doc Gen ([tools](https://developer.box.com/guides/box-mcp/tools)). The docs don't say whether delete was left out on purpose.
- **Risky writes are off by default.** `add_file_shared_link`, `add_folder_shared_link`, `create_collaboration`, `update_collaboration`, `move_file`, `move_folder`, `upload_file_version`, the `update_*_properties` tools, the `set_*_metadata` tools, `update_metadata_template`, `update_hub` and `create_docgen_batch` are marked Off. Tools marked Off "need an admin to turn them on" ([tools](https://developer.box.com/guides/box-mcp/tools)).
- **Admin enablement per category.** The options are "Disable all tools", "Enable read-only tools", "Enable read & write tools" or "Custom configuration". A disabled tool is removed "from the tool list returned to the MCP client". If a session already found it, the call fails with "Tool has been disabled by the enterprise admin. Contact your enterprise admin for more information." The settings "apply globally to the enterprise" ([manage tool access](https://support.box.com/hc/en-us/articles/50837641642643-Manage-Box-MCP-Server-Tool-Access)).
- **Server-side guardrails on writes.** For uploads, "users must specify the destination folder", and "Uploads are limited to folders which are not externally shared to prevent data leaving enterprise boundaries". Hub and Doc Gen writes are "subject to restrictions preventing external sharing" ([support article](https://support.box.com/hc/en-us/articles/49221220102163-Box-MCP-Server)). The docs don't say how the destination folder is obtained. It may be a required parameter or a prompt.
- **Permissions.** "Users can only access content they already have permission to view or edit in Box" ([remote setup](https://developer.box.com/guides/box-mcp/remote)).
- **Audit.** "Every configuration change is logged" ([Box blog](https://blog.box.com/securing-agentic-workflows-box-mcp-server-guardrails)).
- **Disambiguation.** Docs don't say.

## Notes

- Box limits risk by what it leaves out, by tools that are off until an admin enables them, and by server-side restrictions on external sharing. Its docs describe no per-call user confirmation.
