# MCP Atlassian (Jira + Confluence)

| Field | Value |
|---|---|
| Vendor | sooperset; community (not Atlassian) |
| Category | collaboration |
| Tier | 1 |
| Source | open (https://github.com/sooperset/mcp-atlassian @ a423ea5) |
| Language / SDK | Python, FastMCP 3.4.11 on `mcp` 1.30.0 (uv.lock); pyproject pins `fastmcp>=3.4.7,<4`, `mcp>=1.29.1,<2` |
| Hosted endpoint | none (self-hosted; stdio, SSE or streamable HTTP; Helm chart in repo) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none | – | – | – | – | Grep for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` finds nothing in `src/`, `tests/` or `docs/`. The `request_state` hits are Starlette `request.state` test helpers, not SEP-2322. |

## Fallback without client elicitation support

Not applicable. No tool asks the user anything mid-call, and nothing reads `client_capabilities.elicitation`. FastMCP 3.x ships `ctx.elicit()`, but the server doesn't call it.

## Other human-in-the-loop mechanisms

- **Read-only mode** (`READ_ONLY_MODE=true`, [io.py#L26](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/utils/io.py#L26)). It is enforced twice:
  - At listing and call time, every tool tagged `write` is filtered out ([main.py#L340-L357](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/servers/main.py#L340-L357)).
  - The `@check_write_access` decorator raises "Cannot <action> in read-only mode." ([decorators.py#L115-L145](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/utils/decorators.py#L115-L145)).
- **Allowlists.** `ENABLED_TOOLS` is a comma-separated tool allowlist, and toolsets (`toolset:jira_issues`, …) are a coarser allowlist. The code comments call both "security boundaries" enforced at listing and at call time.
- **Annotations.** Write tools set `destructiveHint: True`: 23 in `jira.py` and 15 in `confluence.py`. Examples are `delete_issue` ([jira.py#L2699-L2730](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/servers/jira.py#L2699-L2730)) and `delete_page` ([confluence.py#L1227](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/servers/confluence.py#L1227)). Read tools set `readOnlyHint`. The server leaves confirmation to the client's own annotation-driven approval UI.
- **No confirm argument and no two-step tools.** `delete_issue` deletes as soon as it is called.
- **OAuth setup.** It is an out-of-band interactive CLI wizard that reads answers with `input()` on the terminal ([oauth_setup.py#L423](https://github.com/sooperset/mcp-atlassian/blob/a423ea579955bd4e00bf97ef64effea21f6ad1a3/src/mcp_atlassian/utils/oauth_setup.py#L423)). It is not an MCP flow.

## Notes

- This is a large, popular server (dozens of write tools, including deletes), yet it has no elicitation and no confirm flag. It relies on read-only mode, allowlists and `destructiveHint`.
- The SDK it uses already ships elicitation, so the cost of adopting it would be low.
