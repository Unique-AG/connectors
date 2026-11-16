# Azure DevOps remote MCP server (hosted)

| Field | Value |
|---|---|
| Vendor | Microsoft; official (Azure DevOps-hosted, distinct from the local server in `azure-devops.md`) |
| Category | dev-platform |
| Tier | 2 |
| Source | closed (https://mcp.dev.azure.com) |
| Language / SDK | docs don't say |
| Hosted endpoint | `https://mcp.dev.azure.com/{organization}` (or `https://mcp.dev.azure.com/` without an org) |
| Uses elicitation | unknown (docs never mention elicitation) |
| Mechanism | docs don't say |
| Evidence type | docs only |

Sources:
- [Set up the remote Azure DevOps MCP Server](https://learn.microsoft.com/en-us/azure/devops/mcp-server/remote-mcp-server) ("setup doc")
- [Troubleshoot the remote Azure DevOps MCP Server](https://learn.microsoft.com/en-us/azure/devops/mcp-server/remote-mcp-server-troubleshooting) ("troubleshooting doc")
- [Azure DevOps Remote MCP Server GA blog post](https://devblogs.microsoft.com/devops/azure-devops-remote-mcp-server-ga/)

## Elicitation usages

None documented. Neither Learn page mentions elicitation, confirmation prompts, or approval steps the server raises. The GA blog doesn't cover them either.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none documented | – | – | – | – | – |

Purpose by purpose:
- **Missing project / org (fill-missing-param, disambiguate).** The troubleshooting doc describes an error, not a prompt. "Tool calls fail with 'missing required parameter' errors, typically for the project name ... This error is the most commonly reported error and is expected behavior." The fix it gives is to "Include the project name in your prompt". Without an org in the URL, "you must provide the organization name as context in each tool call" (setup doc). The docs describe no picker for project or team. The local server, by contrast, asks the user to pick (see `azure-devops.md`). In a GA blog comment, a maintainer says "I am not aware of a way to pre-configure the organization when connecting to ADO MCP".
- **Destructive operations.** The tool table marks each action read-only ✅ or ❌. Write and destructive actions are present: `wit_work_item_link_write` `unlink` ("Remove links from a work item"), `pipelines_write` `update_build_stage` ("Cancel, retry, or run a stage"), `run_pipeline`, `enterprise_live_migration_write` `abandon` ("Permanently delete a migration") and `approve_cutover` ("Accept failures and proceed with cutover"), and `enterprise_live_migration_pipelines_write` `delete` ("Delete all pipeline clones for a terminal migration"). The table has no work-item, repo, branch, or wiki delete. The docs mention no confirmation for any of these.
- **Cost confirmation, secret entry:** docs don't say.

## Fallback without client elicitation support

Not applicable, since no elicitation is documented.

## Other human-in-the-loop mechanisms

- **Read-only header.** `X-MCP-Readonly: "true"` "restrict[s] the server to read-only operations ... useful when you want to prevent modifications to Azure DevOps resources" (setup doc).
- **Tool filtering headers.** `X-MCP-Toolsets` (e.g. `repos,wiki,wit`) or `X-MCP-Tools` (named tools). These are set by whoever writes the client config.
- **OAuth scopes.** For custom clients, grant "read scopes when the client uses only read-only MCP tools" and "write or manage scopes only when the client needs the corresponding write operations". "Enabling an MCP tool or toolset doesn't grant additional permissions." An operation "succeeds only when both the application scope and the user's Azure DevOps permissions allow it" (setup doc).
- **Tenant admin controls.** Microsoft Entra only (MSA orgs are not supported). Custom clients need an app registration and "Grant admin consent", which a tenant administrator may have to give. "Conditional Access policies apply to the remote MCP Server the same way they apply to Azure DevOps." Missing assignment or consent shows up as `AADSTS50105` / `AADSTS65001` (troubleshooting doc).
- **Sign-in.** "When prompted, authenticate by using your Microsoft Entra account and select your account" (setup doc, VS Code).
- **Annotations:** docs don't say. The ✅/❌ "Read-only" column is documentation and doesn't say whether the tools carry `readOnlyHint`.
- **Org-wide on/off policy for the remote server:** docs don't say.

## Notes

- From docs alone, the hosted server asks for nothing during a tool call. Missing context comes back as an error, and the user is told to put it in the prompt. Write control is configured up front (headers, scopes, Entra consent).
- The setup doc lists Claude Desktop and Codex as unable to authenticate (no Entra dynamic client registration). Claude Code and Cursor need a custom app registration.
