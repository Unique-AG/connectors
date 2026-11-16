# Moody's MCP (GenAI-Ready Data / "Moody's Credit MCP"), plus Moody's Intelligent Risk Platform MCP

| Field | Value |
|---|---|
| Vendor | Moody's; official. Two separate servers: (A) the Moody's GenAI-Ready Data / Credit MCP and (B) the Intelligent Risk Platform (IRP) Platform MCP Server from Moody's insurance solutions |
| Category | market-data (A); other: insurance risk-modelling platform (B) |
| Tier | 2 |
| Source | closed. (A) https://api.moodys.com/genai-ready-data/m1/mcp. (B) per-tenant, behind Moody's API gateway |
| Language / SDK | docs don't say |
| Hosted endpoint | (A) https://api.moodys.com/genai-ready-data/m1/mcp (Streamable HTTP, MCP OAuth). (B) docs don't give a public URL |
| Uses elicitation | unknown (docs don't mention it) |
| Mechanism | n/a in the docs |
| Evidence type | docs only |

Sources, read 2026-11-16:
- (A) Moody's MCP page [moodys.com/…/model-context-protocol.html](https://www.moodys.com/web/en/us/genai/model-context-protocol.html); press release [Gemini Enterprise](https://www.moodys.com/web/en/us/media-relations/press-releases/moodys-brings-its-decision-grade-intelligence-to-gemini-enterprise-for-financial-services.html) (25 Aug 2026); blogs [GenAI-ready data](https://www.moodys.com/web/en/us/creditview/blog/gen-ai-ready-data-powered-for-adoption.html) (10 Sep 2025) and [Connected intelligence](https://www.moodys.com/web/en/us/insights/ai/connected-intelligence-decision-grade-ai-delivered-where-you-work.html) (29 Jun 2026).
- (B) [Platform MCP Server overview](https://developer.rms.com/platform/docs/platform-mcp-server-overview), [Platform MCP Server tools](https://developer.rms.com/platform/docs/platform-mcp-server-tools).

## Elicitation usages

None documented for either server.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| (A) Connecting in Claude (not a tool call) | browser OAuth, outside MCP calls | auth-oauth | The server "implements the MCP OAuth Specification". Clicking "Connect" sends the user to the Moody's Login Page to enter a "registered email address and password", then back to Claude | docs don't say | [MCP page](https://www.moodys.com/web/en/us/genai/model-context-protocol.html) |
| (B) `execute-api` with no execution credential | none (plain error text) | secret-input (done in chat, not by elicitation) | The tool returns "Auth token not configured. Set it via the set-variable MCP tool." The user then types the key into chat. The documented example prompt is "Use my API key (xxxxxxxxx) to create a connection." `IRP_AUTH` "must be set with every new session" | n/a | [tools](https://developer.rms.com/platform/docs/platform-mcp-server-tools) |

## Fallback without client elicitation support

Docs don't say. For (B), the documented flow already uses chat plus a `set-variable` tool to collect the secret.

## Other human-in-the-loop mechanisms

**(A) GenAI-Ready Data / Credit MCP**
- **Read-only: implied, not stated.** Five tools: `findEntity`, `searchEntityDocuments`, `getEntityRatings`, `getEntityRatingDrivers`, `getEntityScorecard`, all described as finding, searching or returning data ([MCP page](https://www.moodys.com/web/en/us/genai/model-context-protocol.html)).
- **Entitlement.** Users "Request credentials and endpoint URL from Moody's" and sign in with "authorized credentials". What happens without an entitlement: docs don't say.
- **Disambiguation by a lookup tool.** `findEntity` locates entities "by searching with identifiers, names, or related metadata" and returns Moody's entity ID, which the other tools use. No source says the server asks the user to choose between matches.
- **Cost / quota.** Docs don't say.
- **Setup check.** The setup steps end with "Verify that all tools are available and enabled". This is a one-off check by the person installing, not a prompt at call time.

**(B) IRP Platform MCP Server**
- **Not read-only.** `execute-api` "performs actions using Platform API operations". Discovery tools (`search-api-spec`, `get-operation-spec`, `graph-*`, `vector-search`, workflow tools) only read API specs and docs ([overview](https://developer.rms.com/platform/docs/platform-mcp-server-overview)).
- **Two credentials as a gate.** A connection credential set in the MCP client config allows discovery only. A separate execution credential (`IRP_AUTH`) is needed for `execute-api`, and chat clients must set it in every session ([overview](https://developer.rms.com/platform/docs/platform-mcp-server-overview)). The docs warn that credentials typed into a chat become part of the conversation record and are visible to the model. Some organisations may prohibit this.
- **Role-based permissions.** The "IRP Agentic Tools User" role grants Read (discovery) and Write (`execute-api`), and no other rights. Other actions need additional roles, e.g. a principal with only this role cannot model exposures. The docs say there is no read-only role ([overview](https://developer.rms.com/platform/docs/platform-mcp-server-overview)).
- **No confirmation before execution.** The docs describe no approval step before `execute-api` runs an operation.
- **Cost / quota.** Docs don't say.

## Notes

- Server (B) collects a secret by having the user paste it into chat for a `set-variable` tool. The docs themselves warn that this exposes the secret to the model and the transcript. This is the job that secret-input or URL-mode elicitation is designed to keep out of the conversation.
- Moody's says it was "the first financial services firm in the world to launch an MCP app" in Claude ([Connected intelligence](https://www.moodys.com/web/en/us/insights/ai/connected-intelligence-decision-grade-ai-delivered-where-you-work.html)). No readable source describes that app's interactive behaviour.
- The 2026 press materials name the server "Moody's Credit MCP server". The MCP page calls it the Moody's MCP Server at the GenAI-Ready Data URL. We treat them as the same product, but no source states it.
