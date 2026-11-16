# Xero MCP Server

| Field | Value |
|---|---|
| Vendor | Xero; official |
| Category | accounting |
| Tier | 2 |
| Source | open (https://github.com/XeroAPI/xero-mcp-server @ fb4a4bb) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` ^1.23.4 (package-lock resolves 1.32.2) |
| Hosted endpoint | none (stdio via `npx @xeroapi/xero-mcp-server`) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `ElicitRequest`, `elicitInput`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state` anywhere in the repo outside `node_modules`.

## Fallback without client elicitation support

Not applicable. Auth is configured out of band: a Xero custom-connection client ID/secret (client-credentials grant) or a pre-obtained `XERO_CLIENT_BEARER_TOKEN`, both from env vars. No tool ever asks the user for anything mid-call.

## Other human-in-the-loop mechanisms

- Draft-only documents: `create-invoice`, `create-quote` and `create-credit-note` always create `DRAFT` records ([create-xero-invoice.handler.ts#L39](https://github.com/XeroAPI/xero-mcp-server/blob/fb4a4bb88e7095e99830314a517adae6bc58ffc2/src/handlers/create-xero-invoice.handler.ts#L39)), and the matching update tools refuse anything not in `DRAFT` ("Cannot update invoice because it is not a draft") ([update-xero-invoice.handler.ts#L79](https://github.com/XeroAPI/xero-mcp-server/blob/fb4a4bb88e7095e99830314a517adae6bc58ffc2/src/handlers/update-xero-invoice.handler.ts#L79)). A human must approve/send in Xero itself. This is the main safeguard.
- Exceptions: `create-bank-transaction` writes straight to `AUTHORISED` ([create-xero-bank-transaction.handler.ts#L38](https://github.com/XeroAPI/xero-mcp-server/blob/fb4a4bb88e7095e99830314a517adae6bc58ffc2/src/handlers/create-xero-bank-transaction.handler.ts#L38)); `create-payment`, `approve-timesheet`, `delete-timesheet` and `revert-timesheet` act immediately with no confirm argument.
- Scope restriction: `XERO_SCOPES` env var narrows the OAuth scopes requested, which limits what writes can succeed (README, [xero-client.ts#L128](https://github.com/XeroAPI/xero-mcp-server/blob/fb4a4bb88e7095e99830314a517adae6bc58ffc2/src/clients/xero-client.ts#L128)).
- No tool annotations: every tool is registered with `server.tool(name, description, schema, handler)`, so no `readOnlyHint`/`destructiveHint` ([tool-factory.ts#L9-L26](https://github.com/XeroAPI/xero-mcp-server/blob/fb4a4bb88e7095e99830314a517adae6bc58ffc2/src/tools/tool-factory.ts#L9-L26)). No read-only mode, no tool allowlist, no dry-run.

## Notes

- The official Xero server delegates human review to Xero's own DRAFT -> AUTHORISED workflow rather than to the MCP client, which is a domain-native alternative to a confirm-destructive elicitation.
- Payroll tools (approve/revert/delete timesheet) are the riskiest calls and have no gate at all beyond client tool approval.
