# Notion MCP Server (official, local)

| Field | Value |
|---|---|
| Vendor | Notion (makenotion); official |
| Category | collaboration |
| Tier | 2 |
| Source | open (https://github.com/makenotion/notion-mcp-server @ cf16e5c) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` 1.32.2 (package-lock); uses the low-level `Server` class |
| Hosted endpoint | none for this repo. Notion steers users to its separate, closed "Remote Notion MCP" (developers.notion.com/docs/mcp), which this review does not cover. |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none | – | – | – | – | Grep for `elicit`, `requestedSchema`, `InputRequired`, `input_requests`, `request_state` finds nothing. The server declares only `{ capabilities: { tools: {} } }` ([proxy.ts#L140](https://github.com/makenotion/notion-mcp-server/blob/cf16e5c20bfbfb98ecec1227f210ef0ae3abebe5/src/openapi-mcp-server/mcp/proxy.ts#L140)). |

## Fallback without client elicitation support

Not applicable. The server never asks the user anything mid-call.

## Other human-in-the-loop mechanisms

- **Generated annotations.** Tools are generated from Notion's OpenAPI spec. A GET becomes `readOnlyHint: true`, and every other method becomes `destructiveHint: true` ([proxy.ts#L173-L187](https://github.com/makenotion/notion-mcp-server/blob/cf16e5c20bfbfb98ecec1227f210ef0ae3abebe5/src/openapi-mcp-server/mcp/proxy.ts#L173-L187)).
- **Permissions come from the integration token.**
  - The README tells security-conscious users to create a read-only integration ("Read content" capability only).
  - It also tells them to share only selected pages with the integration ([README.md#L104-L112](https://github.com/makenotion/notion-mcp-server/blob/cf16e5c20bfbfb98ecec1227f210ef0ae3abebe5/README.md#L104-L112)).
  - The exposed API subset leaves out some deletes, such as deleting databases.
- **No confirm argument, read-only flag, tool allowlist or two-step flow.**

## Notes

- The README says this repo is "no longer actively maintained or supported" and may be sunset. Notion puts its effort into the hosted Remote Notion MCP ([README.md#L5-L8](https://github.com/makenotion/notion-mcp-server/blob/cf16e5c20bfbfb98ecec1227f210ef0ae3abebe5/README.md#L5-L8)).
- Any elicitation work at Notion would be in the closed hosted server. Probe that separately if it matters.
