# Salesforce Hosted MCP Servers

| Field | Value |
|---|---|
| Vendor | Salesforce; official (Salesforce-hosted servers, distinct from Salesforce DX MCP in `salesforce-dx.md`) |
| Category | other (CRM / enterprise data) |
| Tier | 2 |
| Source | closed (https://api.salesforce.com/platform/mcp/v1/...) |
| Language / SDK | docs don't say |
| Hosted endpoint | `https://api.salesforce.com/platform/mcp/v1/platform/<server>` (production); `.../v1/sandbox/platform/<server>` (sandbox/scratch) |
| Uses elicitation | unknown (docs never mention elicitation) |
| Mechanism | docs don't say |
| Evidence type | docs only |

Sources (developer.salesforce.com, guide "Salesforce Hosted MCP Servers"):
- [General Best Practices](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/general-best-practices.html) ("GBP")
- [Security Best Practices](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/security-best-practices.html) ("SBP")
- [Standard MCP Servers Reference](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/servers-reference.html)
- [SObject Deletes](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/references/reference/sobject-deletes.html), [SObject All](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/sobject-all.html), [SObject Mutations](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/sobject-mutations.html)
- [Headless 360](https://developer.salesforce.com/docs/platform/hosted-mcp-servers/references/reference/headless-360-mcp.html)

## Elicitation usages

None documented. None of the pages read mentions elicitation, server-initiated prompts, or a confirmation the server collects.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none documented | – | – | – | – | – |

Destructive operations and how they are confirmed:
- Deletes exist: `deleteSobjectRecord` and `deleteRelatedRecord`, on the `sobject-deletes` and `sobject-all` servers. Each tool's description contains the instruction "Confirm with the user before deleting." `deleteRelatedRecord` also warns that "deleting a master record in a master-detail relationship also deletes all of its detail records". The read tool on the deletes server says: "Always query and confirm the target record set before invoking a delete — present results to the user for approval when possible." (SObject Deletes, SObject All). This guidance is aimed at the agent. It does not describe a server-side prompt.
- Recovery: "Deleted records go to the Recycle Bin and can be recovered in the Salesforce UI for up to 15 days — no undelete tool is available through MCP" (SObject Deletes).
- Delete tools carry annotations: "delete operations are marked `destructiveHint: true`" (GBP).

Disambiguation, missing parameters, cost confirmation, secret entry: docs don't say. The mutations server tells the agent to look records up first. Its query tool is described as "Use this to look up existing records before creating or updating — for example, to find the Account ID ... or to identify which records need updating" (SObject Mutations). None of the pages describes the server asking the user to choose.

## Fallback without client elicitation support

Not applicable, since no elicitation is documented. The docs place confirmation in the client: "Well-behaved clients use these [annotations] to present appropriate UX—auto-executing read-only tools and requiring confirmation for destructive ones", and "Annotations are hints, not enforcement. Not all clients read or respect them." (GBP).

## Other human-in-the-loop mechanisms

- **Server split by capability.** "SObject Reads - Read and query only, no mutations". "SObject Mutations - Create and update operations, no delete". "SObject Deletes - Delete operations only". "SObject All - Full CRUD" (Standard MCP Servers Reference). The mutations server "excludes potential destructive operations" so that "permanent deletion should require a separate, more deliberate process" (SObject Mutations).
- **Admin enablement.** "Standard servers are disabled by default and can be enabled by an administrator, but their tool sets cannot be modified" (Servers Reference). "MCP servers are disabled by default and require explicit administrative action to enable" (SBP).
- **Client registration control.** "Dynamic client registration is not supported. Administrators must explicitly create and configure External Client Apps". External Client Apps can be linked "to specific profiles and permission sets" (SBP).
- **User permissions.** Calls run "with the same permissions as the user who authorized the connection" (CRUD, FLS, sharing). "No service accounts, no machine-to-machine flows" (SBP).
- **Sign-in.** "Authorization code flow only. The system requires browser-based authentication"; "PKCE is required" (SBP).
- **Narrow access options.** `sobject-reads`, Named Queries, and custom tools (Flows, Apex, REST) that carry their own business logic (SBP).
- **Client-side approval (Headless 360).** "Most MCP clients let you set tool-level restrictions, so configure your client to require your approval before it runs a tool that changes org configuration or alters or deletes data on your behalf." It also offers a `dispatch_readonly` tool that "never changes data or configuration" (Headless 360).
- **Custom tool annotations.** Authors of custom tools are told to set `readOnlyHint`/`destructiveHint`. A tool with no annotations "will trigger unnecessary 'are you sure?' prompts in clients that respect annotations" (GBP).
- **Audit.** MCP traffic is identifiable in API logs via `API_CLIENT_CATEGORY` = `SALESFORCE_HOSTED_MCP` (SBP).

## Notes

- Every human-in-the-loop point in these docs sits in the client (annotations, client tool approval), in the model (tool-description instructions), or with the admin (which servers are enabled, External Client Apps). None of it is in the server.
- Fetching developer.salesforce.com directly returned HTTP 403 to automated clients. The pages were read through a text-rendering proxy. The "Best Practices" URL that search results show returned 404. Its content appears under "General Best Practices".
- Agentforce Vibes and the Agentforce client side (registering third-party MCP servers) were not reviewed.
