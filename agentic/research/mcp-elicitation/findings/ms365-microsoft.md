# Microsoft 365 MCP servers (Work IQ MCP and the Agent 365 workload servers)

| Field | Value |
|---|---|
| Vendor | Microsoft; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (Microsoft-hosted) |
| Language / SDK | docs don't say |
| Hosted endpoint | Work IQ MCP: one endpoint, but the pages reviewed don't give the URL. Legacy workload servers: `https://agent365.svc.cloud.microsoft/agents/tenants/{tenantId}/servers/mcp_MailTools` and similar ([Mail reference](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-mail-tools)) |
| Uses elicitation | no mention |
| Mechanism | unknown (docs don't say) |
| Evidence type | docs only |

**Which servers.** Microsoft currently offers two kinds of server ([Agent 365 MCP server options](https://learn.microsoft.com/en-us/microsoft-agent-365/tooling-servers-overview)):

- **Work IQ MCP** is "A single MCP endpoint with 10 generic tools". It is "generally available as part of the Work IQ API".
- **Workload-specific servers** for Copilot, Calendar, Mail, SharePoint, OneDrive, Teams, User and Word "are only intended for backward compatibility purposes and shouldn't be used in production environments or new projects".

Most of this file covers Work IQ MCP.

## Elicitation usages

The docs don't describe either server asking the user anything during a tool call.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Connecting a client to Work IQ MCP | n/a (client-run Entra OAuth, not described as elicitation) | auth-oauth | The user signs in with Microsoft Entra ID. "MCP clients automatically discover the authentication configuration through the `/.well-known/oauth-protected-resource` endpoint" | docs don't say | [Work IQ MCP overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/overview) |

## Fallback without client elicitation support

Docs don't say.

## Other human-in-the-loop mechanisms

- **Writes are off by default and controlled by admin policy, not by the user.** A tenant policy layer "evaluates each tool request and blocks mutation operations by default. Administrators can enable supported create, update, delete, and action requests through tenant policy" ([tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)). The blocked operations include "action requests that modify data, such as sending email" ([policy governance](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp)). The policy is written in Rego and evaluates path, operation, request content, and user and tenant context.
- **Policy granularity.** "In the initial release, Work IQ MCP provides tenant-level policy control." "Per-user, per-app, per-agent, or scenario-specific policy templates aren't part of the initial policy control surface" ([policy governance](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp)).
- **What a denied call looks like.** The request fails, and clients should "Surface policy-denied responses clearly so administrators can review tenant policy configuration" ([policy governance](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp)). The server does not ask the user to approve the call.
- **Destructive tools exist and have no documented confirmation.** `delete_entity` "Deletes an entity", and its example deletes `/me/messages/{id}`. `do_action` "Runs a side-effect action such as sending mail, copying, or moving items" ([tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)). The reference describes no confirmation parameter and no prompt for either tool.
- **Path allow and block lists.** The allowed path prefixes are `/me/`, `/users/` and `/sites/`. The segments `/authentication/` and `/servicePrincipals/` are blocked, and "The complete list ... depends on per-tenant policy configuration" ([tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)).
- **Read limits.** Collections get a default `$top` of 25 with a cap of 100, chat messages are capped at 10 per request, and `$skip` and `$skiptoken` are blocked ([tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)).
- **User permissions still apply.** "Policy can't grant access beyond what the signed-in user is already allowed to access" ([policy governance](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/policy-governance-mcp)).
- **Admin tool registry.** "Administrators use **Agents** > **Tools** in the Microsoft 365 admin center". "For supported MCP servers, administrators can also view and control individual tools" ([Agent 365 MCP server options](https://learn.microsoft.com/en-us/microsoft-agent-365/tooling-servers-overview)). What appears can vary by "tenant, region, rollout status, licensing, administrator approval, and organizational policy".
- **Legacy Mail server.** The tools are `createMessage` ("Create a draft email"), `sendDraft`, `sendMail` ("Send an email as the signed-in user"), `reply`, `replyAll`, `updateMessage` and `deleteMessage` ("Deletes a message from the signed-in user's mailbox"). "Draft messages can be created, updated, and sent separately" ([Mail reference](https://learn.microsoft.com/en-us/microsoft-copilot-studio/mcp-mail-tools)). The page describes no confirmation step.
- **Disambiguation.** Docs don't say. The `ask` tool takes a `conversationId` so a Copilot conversation can continue across calls ([tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference)). Nothing says the server asks the user to choose between candidates.

## Notes

- Work IQ MCP governs writes with an admin-side default deny, and its docs describe no per-call user confirmation. Of the servers in this batch, it is the only one whose docs say write tools are blocked unless an admin allows them.
- The `delete_entity` parameter table describes `agentId` as "The ID of a specific agent to route the question to", while the other entity tools say "Reserved for future use." This looks like a copy error in the docs.
