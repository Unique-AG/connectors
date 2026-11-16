# Cloudflare MCP servers

| Field | Value |
|---|---|
| Vendor | Cloudflare; official |
| Category | infra |
| Tier | 3 |
| Source | open (https://github.com/cloudflare/mcp-server-cloudflare @ a21972e; also https://github.com/cloudflare/mcp @ 7eb0b52, the recommended "code mode" API server; SDK helpers in https://github.com/cloudflare/agents @ 9b73399) |
| Language / SDK | TypeScript. mcp-server-cloudflare: `@modelcontextprotocol/server` 2.0.0 + `@modelcontextprotocol/sdk` 1.30.0, `agents` 0.20.1. cloudflare/mcp: `@modelcontextprotocol/server` 2.3.1 |
| Hosted endpoint | https://mcp.cloudflare.com/mcp (API), plus per-product servers such as https://docs.mcp.cloudflare.com/mcp, https://browser.mcp.cloudflare.com/mcp, https://dex.mcp.cloudflare.com/mcp |
| Uses elicitation | no (Cloudflare's own servers). The `agents` SDK ships helpers and examples for both mechanisms |
| Mechanism | n/a in the servers. `agents` SDK: legacy `elicitation/create` (`McpAgent.elicitInput`) and 2026-07-28 `inputRequired` examples |
| Evidence type | code |

## Elicitation usages

None in either server repo. `grep -i elicit` over mcp-server-cloudflare and cloudflare/mcp returns nothing. The only hit is a type: `AccountToolResult = CallToolResult | InputRequiredResult` in [packages/mcp-common/src/account-tool.ts#L12](https://github.com/cloudflare/mcp-server-cloudflare/blob/a21972e219289337731a066befb5c66886b9ce7b/packages/mcp-common/src/account-tool.ts#L12). It mirrors the v2 SDK `ToolCallback` return type, and no handler returns an `InputRequiredResult`.

What the `agents` SDK offers to third parties (Cloudflare's own servers do not use it):

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `McpAgent.elicitInput()` (stateful Durable Object server) | form / url | generic helper | Sends `elicitation/create` with caller's `message` + `requestedSchema` over the session transport, keeps the DO alive, 60 s timeout | Returns the raw `ElicitResult` to the caller. Timeout rejects "Elicitation request timed out". No client-capability check before sending | [packages/agents/src/mcp/server/legacy-agent.ts#L416](https://github.com/cloudflare/agents/blob/9b73399c7cee9550c19146b7f76a735a10700ada/packages/agents/src/mcp/server/legacy-agent.ts#L416) |
| Example `increase-counter` (legacy) | form | fill-missing-param | "By how much should the counter increase?" `{amount: number}` | Text "Counter increase cancelled." | [examples/mcp-elicitation/src/index.ts#L71](https://github.com/cloudflare/agents/blob/9b73399c7cee9550c19146b7f76a735a10700ada/examples/mcp-elicitation/src/index.ts#L71) |
| Example URL-mode "link an external account" (legacy) | url | auth-oauth (demo) | URL + `elicitationId` | Text "Account connection cancelled." | [examples/mcp-elicitation/src/index.ts#L127](https://github.com/cloudflare/agents/blob/9b73399c7cee9550c19146b7f76a735a10700ada/examples/mcp-elicitation/src/index.ts#L127) |
| Example `increase-counter` (stateless MRTR) | form | fill-missing-param, then confirm | Round 1 `amount`, round 2 `{confirm: boolean}`; signed `requestState` (HMAC key `MRTR_REQUEST_STATE_KEY`) carries intermediate values | Text "Counter increase cancelled." | [examples/mcp-elicitation-mrtr/src/index.ts#L94](https://github.com/cloudflare/agents/blob/9b73399c7cee9550c19146b7f76a735a10700ada/examples/mcp-elicitation-mrtr/src/index.ts#L94) |

The `agents` MCP *client* (`MCPClientManager`) also declares form/url elicitation capability when handlers are configured ([packages/agents/src/mcp/client/manager.ts#L466](https://github.com/cloudflare/agents/blob/9b73399c7cee9550c19146b7f76a735a10700ada/packages/agents/src/mcp/client/manager.ts#L466)).

## Fallback without client elicitation support

Not applicable to the servers. The SDK's `elicitInput` has no fallback of its own: it sends regardless and the caller handles the error or timeout.

## Other human-in-the-loop mechanisms

- **Account disambiguation by error, not by prompt.** When a token spans several accounts and neither a `cf-account-id` header nor an `account_id` argument is given, the tool returns `isError` "account_id is required because your credentials can access multiple Cloudflare accounts..." with `available_accounts: [{id, name}]`. The model is left to pick or ask ([packages/mcp-common/src/account-manager.ts#L114](https://github.com/cloudflare/mcp-server-cloudflare/blob/a21972e219289337731a066befb5c66886b9ce7b/packages/mcp-common/src/account-manager.ts#L114)). Multi-account tokens also get the account list in the server instructions. This is a textbook `disambiguate` elicitation that Cloudflare chose to do through the model.
- **OAuth step-up instead of URL elicitation** (cloudflare/mcp). A tool that hits a missing OAuth scope records an `insufficient_scope` challenge. The server then answers HTTP 403 + `WWW-Authenticate`, or for clients known to read it (Codex, ChatGPT) puts the challenge in the tool result `_meta["mcp/www_authenticate"]` ([src/scope-challenge.ts#L19](https://github.com/cloudflare/mcp/blob/7eb0b5258c4265503b3fce8842b96adc5422fa69/src/scope-challenge.ts#L19), [src/clients.ts#L42](https://github.com/cloudflare/mcp/blob/7eb0b5258c4265503b3fce8842b96adc5422fa69/src/clients.ts#L42)).
- **Annotations.** `destructiveHint: true` on delete tools (D1, KV, R2, Hyperdrive), e.g. [apps/workers-bindings/src/tools/d1.tools.ts#L119](https://github.com/cloudflare/mcp-server-cloudflare/blob/a21972e219289337731a066befb5c66886b9ce7b/apps/workers-bindings/src/tools/d1.tools.ts#L119). The code-mode `execute` tool on mcp.cloudflare.com is `destructiveHint: true` ([src/tools/execute.ts#L590](https://github.com/cloudflare/mcp/blob/7eb0b5258c4265503b3fce8842b96adc5422fa69/src/tools/execute.ts#L590)).
- **Prompt-text confirmation.** DEX remote-capture tools tell the model to "Always ask for confirmation from the user that the targeted email and device are correct before executing a capture" ([apps/dex-analysis/src/tools/dex-analysis.tools.ts#L203](https://github.com/cloudflare/mcp-server-cloudflare/blob/a21972e219289337731a066befb5c66886b9ce7b/apps/dex-analysis/src/tools/dex-analysis.tools.ts#L203)).
- OAuth scopes chosen at consent, and API permission refusals explained back to the agent (`src/api-refusals.ts` in cloudflare/mcp).

## Notes

- Cloudflare builds both SDK and servers. The SDK has first-class elicitation, including a stateless SEP-2322 example with signed `requestState`, but none of its production MCP servers use it.
- The legacy example uses a `confirm: boolean` tool argument *and* then elicits. The argument-based confirm is the same pattern other servers use as a fallback.
