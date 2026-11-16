# Atlassian Rovo MCP v2 (official, hosted)

| Field | Value |
|---|---|
| Vendor | Atlassian; official |
| Category | collaboration |
| Tier | 1 |
| Source | closed (https://mcp.atlassian.com/v2/mcp) |
| Language / SDK | unknown (hosted) |
| Hosted endpoint | https://mcp.atlassian.com/v2/mcp (OAuth 2.1 with dynamic client registration; API-token auth exists if an org admin enables it) |
| Uses elicitation | no (none observed on any probed tool) |
| Mechanism | n/a. Negotiates 2026-07-28 under `auto` and also accepts 2025-11-25 under `legacy` |
| Evidence type | live probe |

## Elicitation usages

None. The probe was run on 2026-11-16 against the PLATFORM space, on a throwaway child page that was deleted after each run. It made 4 runs:

| Run | Protocol | Client elicitation | Elicitations | Outcome |
|---|---|---|---|---|
| decline | 2026-07-28 | declared | 0 | every call succeeded |
| accept | 2026-07-28 | declared | 0 | every call succeeded |
| no-elicitation | 2026-07-28 | not declared | 0 | every call succeeded, with identical results |
| decline, legacy | 2025-11-25 | declared | 0 | every call succeeded |

Calls in each run:
- `getAccessibleAtlassianResources` and `searchJiraIssuesUsingJql` (reads)
- `createConfluenceContent` (page) and `updateConfluenceContent`
- `executeWrite` `watchConfluenceContent`
- `executeDestructive` `unwatchConfluenceContent` and `executeDestructive` `removeConfluenceContentPermissions`

Publishing this research to Confluence through the same server added 5 creates and 1 update, also with no elicitation.

## Fallback without client elicitation support

Not applicable. The server behaves identically whether or not the client declares elicitation, including on `executeDestructive`.

## Other human-in-the-loop mechanisms

- Tool surface split by risk. 26 tools are listed. Beyond the dedicated Confluence and Jira tools, about 400 operations are reachable through `discover` and then `executeRead`, `executeWrite` or `executeDestructive`. Only `executeDestructive` carries `destructiveHint: true`; `executeRead` and the reads carry `readOnlyHint`. Gating is left to the client: a host that asks before any `destructiveHint` tool will ask before every destructive operation, because they all go through one tool.
- No page-delete operation is exposed at all (`discover` for "delete confluence page/content" returns none), so the most damaging Confluence action is not available to an agent.
- Tool descriptions steer the model toward safer flows: suggestions instead of direct edits ("use addConfluenceContentSuggestions"), and snapshot tokens for optimistic concurrency on edits, which prevents blind overwrites.
- OAuth scopes and admin settings decide which products and operations the connection can reach. API-token auth must be enabled by an org admin.

## Notes

- `getConfluenceContent` takes `content_id` / `content_url` (snake case), while `updateConfluenceContent` takes `contentId` / `contentUrl`.
- Unbounded JQL (`ORDER BY created DESC` with no restriction) is rejected with a 400.
- Atlassian's own client guidance says the v1 endpoints are deprecated (removal 2027-03-01); the v2 tool set differs from v1 (`createConfluenceContent` replaces `createConfluencePage` etc.).
