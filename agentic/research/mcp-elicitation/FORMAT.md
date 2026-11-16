# Finding format

One file per MCP server: `findings/<slug>.md`. Keep each section short; link evidence instead of quoting code.

```markdown
# <MCP name>

| Field | Value |
|---|---|
| Vendor | <company or maintainer; official or community> |
| Category | collaboration / payments / trading / banking / accounting / market-data / dev-platform / infra / other |
| Tier | 1 / 2 / 3 |
| Source | open (<repo URL> @ <short SHA>) / closed (<hosted URL>) |
| Language / SDK | <language>, <MCP SDK + version from lockfile/manifest> |
| Hosted endpoint | <URL or "none"> |
| Uses elicitation | yes / no / unknown |
| Mechanism | legacy `elicitation/create` request / 2026-07-28 `InputRequiredResult` / both / n/a |
| Evidence type | code / live probe / docs only |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `<tool>` | form / url | <purpose> | <message + schema fields> | <behaviour> | <permalink file#Lline> |

Purpose is one of: `confirm-destructive`, `confirm-cost`, `fill-missing-param`, `disambiguate`,
`auth-oauth`, `secret-input`, `consent-data-sharing`, `other (<say what>)`.

## Fallback without client elicitation support

<What the server does when the client does not declare the capability: errors, proceeds silently,
falls back to a `confirm`-style argument, hides the tool, ...>

## Other human-in-the-loop mechanisms

<Confirmation arguments, two-step "prepare/execute" tools, read-only mode flags, tool allowlists,
`destructiveHint`/`readOnlyHint` annotations — anything that does the job elicitation could do.>

## Notes

<Anything surprising. Open questions.>
```
