# QuickBooks Online MCP Server

| Field | Value |
|---|---|
| Vendor | Intuit; official |
| Category | accounting |
| Tier | 2 |
| Source | open (https://github.com/intuit/quickbooks-online-mcp-server @ 31a1dd5) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` ^1.26.0 (package-lock resolves 1.30.0) |
| Hosted endpoint | none (stdio only) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `ElicitRequest`, `elicitInput`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` anywhere in the repo outside `node_modules`. The server declares only `capabilities: { tools: {} }` ([qbo-mcp-server.ts#L10-L20](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/server/qbo-mcp-server.ts#L10-L20)).

## Fallback without client elicitation support

Not applicable, but the server does run an interactive OAuth flow that URL-mode elicitation would fit, entirely out of band:

- First tool call with no refresh token / realm ID: `authenticate()` calls `startOAuthFlow()` from inside the tool call ([quickbooks-client.ts#L595-L603](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/clients/quickbooks-client.ts#L595-L603)). It binds a localhost callback server, prints the authorize URL to the console and tries `open(authUri)` to launch the local browser, then blocks the tool call until the callback arrives ([#L400-L411](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/clients/quickbooks-client.ts#L400-L411)).
- In `production` it refuses to do this (Intuit rejects localhost redirects) and throws "QuickBooks authorization is invalid or expired and cannot be renewed automatically in production. Re-authorize ... then restart the server." ([#L239-L256](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/clients/quickbooks-client.ts#L239-L256)).
- Recommended path is `npm run auth` (a terminal script, [auth-server.ts](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/auth-server.ts)) that writes tokens to `.env` before the MCP server starts.

## Other human-in-the-loop mechanisms

- CRUD-category kill switches: `QUICKBOOKS_DISABLE_WRITE`, `QUICKBOOKS_DISABLE_UPDATE`, `QUICKBOOKS_DISABLE_DELETE` stop `create_*`, `update_*`, `delete_*` tools from being registered (prefix match on the tool name) ([register-tool.ts#L20-L60](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/helpers/register-tool.ts#L20-L60), [#L115-L119](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/helpers/register-tool.ts#L115-L119)). Read tools cannot be disabled. All on by default.
- Optimistic concurrency: delete/update tools require the entity's `SyncToken`, so the model must read the current record first ([delete-bill.tool.ts#L7-L12](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/tools/delete-bill.tool.ts#L7-L12)). Not a human check, but it blocks blind deletes.
- No tool annotations (`server.tool(name, description, {params}, handler)` at [register-tool.ts#L162](https://github.com/intuit/quickbooks-online-mcp-server/blob/31a1dd5c3e170e368dbff651abbaf61aabde6ed9/src/helpers/register-tool.ts#L162)), no confirm or dry-run arguments, no "send" confirmation. 20 `delete_*` tools (several void invoices, payments, sales receipts) act immediately.

## Notes

- An unknown-parameter warning is prepended to tool results because zod strips undeclared fields silently; the comment cites an invoice sent with a blank ship date. A data-integrity guard, not a human gate.
- The mid-call OAuth flow prints to stdout via `console.log` while the stdio transport owns stdout; this looks like it would corrupt the JSON-RPC stream on a cold start (not verified by running).
