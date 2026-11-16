# Microsoft 365 MCP Server (Softeria)

| Field | Value |
|---|---|
| Vendor | Softeria; community (not Microsoft) |
| Category | collaboration |
| Tier | 1 |
| Source | open (https://github.com/softeria/ms-365-mcp-server @ 29ebda2) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` 1.32.0 (package-lock) |
| Hosted endpoint | none (self-hosted; stdio or `--http` with an OAuth proxy to Entra) |
| Uses elicitation | no |
| Mechanism | n/a (a text-based `confirm: true` gate instead) |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none | – | – | – | – | The word "elicitation" appears only in a comment and in the docs, describing the confirm gate as able to "coexist with client-side elicitation prompts (MCP Elicitation API)" ([graph-tools.ts#L682-L691](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/graph-tools.ts#L682-L691), [deployment.md#L239](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/docs/deployment.md#L239)). There are no `elicitInput` calls. |

## Fallback without client elicitation support

Not applicable. Elicitation is never used, so nothing depends on client support. The confirm gate below works with every client because it only needs the model to resend the call with an extra argument.

## Other human-in-the-loop mechanisms

- **Confirm gate on destructive tools.** It is opt-in through `MS365_MCP_REQUIRE_CONFIRM=true` and off by default.
  - **Scope.** Every POST/PATCH/PUT/DELETE tool counts as destructive, except POSTs that `endpoints.json` flags `readOnly` (`isDestructiveOperation` in `src/lib/destructive-ops.ts`).
  - **Schema.** Those tools get an optional `confirm: boolean` parameter whose description says "Set to true only after the user has explicitly approved this action" ([graph-tools.ts#L4097-L4100](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/graph-tools.ts#L4097-L4100), [param-descriptions.ts#L156-L159](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/lib/param-descriptions.ts#L156-L159)).
  - **Refusal.** A call without `confirm: true` returns `isError: true` with `{"error":"confirmation_required", tool, method, destructive: true, message: "This tool modifies user data. Re-call with parameter \"confirm\": true after the user has explicitly approved the operation."}`. It never reaches Graph and is not audited ([graph-tools.ts#L3049-L3073](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/graph-tools.ts#L3049-L3073)).
- **Read-only mode.** `--read-only` drops every non-GET tool except POSTs flagged `readOnly` ([auth.ts#L502-L506](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/auth.ts#L502-L506)).
- **Tool filtering.**
  - `--enabled-tools <regex>`, `--enabled-tools-file` and `--preset` choose which tools are exposed.
  - `--allowed-scopes` adds a policy denial, logged as `tool.denied`.
- **Annotations.** `readOnlyHint` / `destructiveHint` come from the HTTP method plus the `readOnly` flag ([graph-tools.ts#L4150-L4161](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/graph-tools.ts#L4150-L4161)).
- **Prompt-level hints.**
  - Some `llmTip` strings tell the model to "Confirm with the user before calling", for example deleting a SharePoint list column ([endpoints.json#L2505](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/endpoints.json#L2505)).
  - The `login` tool returns the device-code text (`{"error":"device_code_required", message}`) for the model to relay to the user ([auth-tools.ts#L85-L103](https://github.com/softeria/ms-365-mcp-server/blob/29ebda21cfb707922d34ab56ccce4dabd1a00004/src/auth-tools.ts#L85-L103)). This does what URL-mode elicitation would, as plain text.

## Notes

- This is the clearest "why not elicitation" example in the batch. The maintainers chose a model-mediated `confirm` flag because it works on every client, and they say outright that it could sit alongside elicitation.
- The weakness of the gate is that the LLM can set `confirm: true` itself. The server cannot tell whether a human actually approved.
- The audit log skips confirm-gate refusals.
