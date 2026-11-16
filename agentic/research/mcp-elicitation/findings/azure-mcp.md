# Azure MCP Server (microsoft/mcp)

| Field | Value |
|---|---|
| Vendor | Microsoft; official |
| Category | infra |
| Tier | 1 |
| Source | open (https://github.com/microsoft/mcp @ d97c4ee) |
| Language / SDK | C# / .NET, `ModelContextProtocol` + `ModelContextProtocol.AspNetCore` 2.2.0 (Directory.Packages.props) |
| Hosted endpoint | none (local stdio, or self-hosted `--transport http`) |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request (no `InputRequired` / `inputRequests` / `requestState` anywhere in the repo) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/`

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| Every tool whose `[CommandMetadata]` has `Destructive = true` or `Secret = true` (central tool-loader gate, runs before the command). ~161 command files set `Destructive = true` (ResilienceManagement 25, AzureBackup 18, Fabric 17, SreAgent 15, ManagedLustre 13, Compute 10, Sql 8, ...); 18 set `Secret = true` (e.g. `keyvault secret get/create`, `appservice webapp settings get`, VM/VMSS create/delete, Fabric item definition/schedules) | form | confirm-destructive and/or consent-data-sharing (secret exposure) | One consolidated prompt. Message varies by flags: "⚠️ DESTRUCTIVE OPERATION WARNING: The tool '<tool>' may delete or modify existing resources... Do you want to continue...?", "⚠️ SECURITY WARNING: ... may expose secrets or sensitive information...", or both. Schema: `decision` (required, titled single-select enum `Approve`=`accept` / `Reject`=`reject`) | Approval requires BOTH envelope `action == accept` AND `decision == "accept"`; otherwise `isError` "Operation cancelled by user." Any elicitation exception -> `isError` "Elicitation failed for tool '<tool>': ... Operation not executed for security." | [core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/BaseToolLoader.cs#L261-L383](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/BaseToolLoader.cs#L261-L383); called from [CommandFactoryToolLoader.cs#L196](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/CommandFactoryToolLoader.cs#L196), [NamespaceToolLoader.cs#L429](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/NamespaceToolLoader.cs#L429), [SingleProxyToolLoader.cs#L566](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/SingleProxyToolLoader.cs#L566) |
| Resiliency Agent tools (`resiliencyagent` area: guidance `get`, architecture `assess`, IaC `generate`, bicep/arm/terraform `review`) when the hosted A2A agent returns an "awaiting user" turn | form | fill-missing-param (agent clarifying questions, up to 20 rounds per call) | Message = the remote agent's question (default "The Azure Resiliency Agent needs more information to continue."); schema `answer` (required string, title "Your answer") | Non-accept or empty answer -> conversation completed with state `canceled` (HTTP 400 status in the command response); Q/A pairs echoed back in the result as `elicitationResponses` | [tools/Azure.Mcp.Tools.ResiliencyAgent/src/Commands/ResiliencyAgentCommand.cs#L127-L155](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/tools/Azure.Mcp.Tools.ResiliencyAgent/src/Commands/ResiliencyAgentCommand.cs#L127-L155), [#L429-L479](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/tools/Azure.Mcp.Tools.ResiliencyAgent/src/Commands/ResiliencyAgentCommand.cs#L429-L479) |
| `resiliencyagent file attach` | form | consent-data-sharing (upload a local file to a hosted agent) | "Share this local file with the hosted Azure Resiliency Agent?" + canonical path, MIME type, size, retention explanation; schema `approve` (required boolean, default `false`, title "Share this file") | Anything but accept + `approve == true` -> `OperationCanceledException`, response 400 "The file attachment was cancelled."; file bytes never read | [tools/Azure.Mcp.Tools.ResiliencyAgent/src/Commands/File/FileAttachCommand.cs#L95-L141](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/tools/Azure.Mcp.Tools.ResiliencyAgent/src/Commands/File/FileAttachCommand.cs#L95-L141) |
| Proxied child MCP servers (registry / external servers loaded by `ServerToolLoader`, `SingleProxyToolLoader`) | whatever the child sends | other (pass-through) | Child server's `elicitation/create` is forwarded verbatim to the upstream client via `server.ElicitAsync` | Child's own handling | [BaseToolLoader.cs#L228-L235](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Areas/Server/Commands/ToolLoading/BaseToolLoader.cs#L228-L235) |

## Fallback without client elicitation support

- Capability check: `server.ClientCapabilities?.Elicitation != null` ([McpServerElicitationExtensions.cs#L198](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/core/Microsoft.Mcp.Core/src/Extensions/McpServerElicitationExtensions.cs#L198)).
- Destructive/secret gate fails closed: `isError` "This tool <reason> and requires user consent, but the client does not support elicitation. Operation rejected for security." Tools stay listed; they just refuse at call time.
- Opt-out: server start flag `--dangerously-disable-elicitation` (formerly `--insecure-disable-elicitation`) skips the gate with only a log warning ("Proceeding without user consent"). Documented as for CI / disposable environments; their own integration tests start the server with it.
- Resiliency Agent: no flag bypass. Clarifying questions throw "The Resiliency Agent needs to ask a follow-up question, but this client does not support elicitation, so the conversation cannot continue."; `file attach` throws "This client cannot request the user confirmation required before reading a local file." The `--dangerously-disable-elicitation` flag does not apply to these command-level prompts.
- TROUBLESHOOTING.md tells users to upgrade to VS Code 1.102+ when they see the "elicitation is unsupported" error ([TROUBLESHOOTING.md#L306](https://github.com/microsoft/mcp/blob/d97c4ee2b74357c3e4353e30606656c3530fa0c9/servers/Azure.Mcp.Server/TROUBLESHOOTING.md#L306)).

## Other human-in-the-loop mechanisms

- `--read-only` server flag (VS Code extension setting `azureMcp.readOnly`) hides write tools.
- `--namespace`, `--tool`, `--mode` tool allowlists.
- Per-command metadata mapped to MCP annotations: `Destructive` (default `true`, per the spec default), `ReadOnly`, `Idempotent`, `OpenWorld`, plus non-standard `Secret` and `LocalRequired`; the same flags drive the elicitation gate.

## Notes

- Elicitation is a framework-level policy, not per-tool code: any command author who sets `Destructive = true` or `Secret = true` gets a consent prompt for free. Because `Destructive` defaults to `true`, a command that forgets to set it gets prompted.
- They hit client bugs repeatedly (CHANGELOG): "Form mode elicitation requests require a requested schema" error from a client, then an untitled-enum schema that GitHub Copilot CLI could not render (switched to `TitledSingleSelectEnumSchema`), then a fix because clients return `action: accept` when the user picked "Reject" in the form, which is why approval now checks the field value too.
- `Secret` prompts fire on reads (e.g. `keyvault secret get`) — consent to put a secret into model context, not just destructive-write confirmation.
- No URL mode, no 2026-07-28 multi-round-trip support at this SHA.
