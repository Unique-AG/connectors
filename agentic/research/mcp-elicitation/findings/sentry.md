# Sentry MCP

| Field | Value |
|---|---|
| Vendor | Sentry; official |
| Category | dev-platform |
| Tier | 3 |
| Source | open (https://github.com/getsentry/sentry-mcp @ fcc022a) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` 1.32.2 (pnpm catalog); Cloudflare `agents` 0.32.0 for the hosted Worker |
| Hosted endpoint | https://mcp.sentry.dev/mcp |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. A case-insensitive grep for `elicit`, `requestedSchema`, `InputRequired`, `inputRequests` and `requestState` over the whole repo (source, docs, openspec, tests) finds nothing.

## Fallback without client elicitation support

Not applicable. No tool behaves differently based on the client's capabilities.

## Other human-in-the-loop mechanisms

Permalink base: `https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/`

- **Skills, granted at OAuth consent.** The OAuth approval screen bundles tools into skills: `inspect`, `seer` (default on), `triage` and `project-management` (default off). The server registers only the tools of the granted skills ([packages/mcp-core/src/skills.ts#L27](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/packages/mcp-core/src/skills.ts#L27)). Write and delete tools (`update_issue`, `delete_alert_rule`, `delete_uptime_monitor`, ...) only exist if the user ticked a write skill. That consent happens once, up front, not per action.
- **Annotations.** Every tool sets `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`. There are 12 catalog tools with `destructiveHint: true`, for example [delete-alert-rule.ts#L40](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/packages/mcp-core/src/tools/catalog/delete-alert-rule.ts#L40). The server relies on the client to prompt on these.
- **Project and org constraints** set by the URL path (`/mcp/<org>/<project>`) narrow every call. `delete_alert_rule` refuses to delete an alert shared outside the constrained project.
- **Tool descriptions as soft guidance.** They point the model to inspect first (`get_alert_rule` before `delete_alert_rule`) and to prefer reversible actions ("disable it instead").
- `execute_tool` (catalog dispatcher) is marked `destructiveHint: true` because it can call any granted tool ([execute-tool.ts#L140](https://github.com/getsentry/sentry-mcp/blob/fcc022ac433df17cab3862ef6905ad02b4bf2117/packages/mcp-core/src/tools/special/execute-tool.ts#L140)).

## Notes

- The SDK version (1.32.2) supports `elicitInput`, so the absence is a choice, not a limitation. Sentry put its human-in-the-loop entirely at authorization time (skills on the consent screen) plus annotations.
- `analyze_issue_with_seer` starts a paid AI run and is `readOnlyHint: false`. There is no cost confirmation.
