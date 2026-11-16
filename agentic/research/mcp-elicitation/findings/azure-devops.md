# Azure DevOps MCP Server (local)

| Field | Value |
|---|---|
| Vendor | Microsoft; official |
| Category | dev-platform |
| Tier | 2 |
| Source | open (https://github.com/microsoft/azure-devops-mcp @ 65868ea) |
| Language / SDK | TypeScript, `@modelcontextprotocol/sdk` 1.32.0 (pinned in package.json / package-lock.json) |
| Hosted endpoint | Remote MCP Server (preview, closed source; see learn.microsoft.com/azure/devops/mcp-server/remote-mcp-server). This finding covers only the open local server |
| Uses elicitation | yes |
| Mechanism | legacy `elicitation/create` request (`server.server.elicitInput`) |
| Evidence type | code |

## Elicitation usages

Permalink base: `https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/`

All usages go through two helpers in [src/shared/elicitations.ts](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/shared/elicitations.ts): `elicitProject` ([#L17-L57](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/shared/elicitations.ts#L17-L57)) and `elicitTeam` ([#L59-L99](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/shared/elicitations.ts#L59-L99)). Each fires only when the tool's optional `project` / `team` argument is omitted AND the `ado_mcp_project` / `ado_mcp_team` env default is unset.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| `core_list_project_teams` without `project` | form | fill-missing-param | "Select the Azure DevOps project to list teams for."; schema `project` (required string, `oneOf` of up to 100 project names fetched live) | Non-accept -> plain (non-error) text result "Project selection cancelled." | [src/tools/core.ts#L42](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/core.ts#L42) |
| `work` (actions `list_team_iterations`, `list_iterations`, `get_team_settings`, `get_team_capacity`, `get_iteration_capacities`) without `project` / `team` | form | fill-missing-param | Project picker as above with action-specific message; then team picker "Select the Azure DevOps team to list iterations for." / "...get settings for."; schema `team` (required string, `oneOf` of the project's teams) | "Project selection cancelled." / "Team selection cancelled." (not `isError`) | [src/tools/work.ts#L43](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L43), [#L50](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L50), [#L72](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L72), [#L116](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L116), [#L123](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L123), [#L160](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L160), [#L207](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L207) |
| `wit_work_item` (get_batch, comments, revisions, iteration items, work item type, ...) without `project` | form | fill-missing-param | Project picker, e.g. "Select the Azure DevOps project to retrieve work items for." | "Project selection cancelled." | [src/tools/work-items.ts#L190](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L190), [#L229](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L229), [#L240](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L240), [#L252](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L252), [#L289](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L289), [#L301](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L301) |
| `wit_query` without `project` | form | fill-missing-param | "Select the Azure DevOps project for <action>." | as above | [src/tools/work-items.ts#L362](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L362) |
| `wit_backlog` without `project` / `team` | form | fill-missing-param | Project then team picker, "Select the Azure DevOps project/team to <label> for." | as above | [src/tools/work-items.ts#L439](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L439), [#L447](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L447) |
| `wit_work_item_attachment`, `wit_work_item_attachment_upload`, `wit_work_item_attachment_link` without `project` | form | fill-missing-param | Project picker ("...to retrieve the work item attachment from." / "...to upload the work item attachment to." / "...containing the work item to link the attachment to.") | as above | [src/tools/work-items.ts#L529](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L529), [#L623](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L623), [#L657](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L657) |
| `wit_work_item_write` (create, create children), `wit_work_item_comment_write`, `wit_work_item_link_write` (link, unlink, artifact link) without `project` | form | fill-missing-param | Project picker ("...to create the work item in.", "...to link work items in.", ...) | as above | [src/tools/work-items.ts#L768](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L768), [#L870](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L870), [#L985](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L985), [#L1153](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L1153), [#L1210](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L1210), [#L1293](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work-items.ts#L1293) |

## Fallback without client elicitation support

- No capability check in the server code. `elicitInput` is called unconditionally when the parameter is missing. The SDK's own `elicitInput` refuses when the client did not declare form elicitation and throws; the tool handlers wrap everything in `try/catch` and return `isError` text such as "Error fetching team iterations: <message>" ([src/tools/work.ts#L229-L243](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/tools/work.ts#L229-L243)). The SDK error wording was not checked against the 1.32.0 package source, since nothing was installed.
- Effective fallbacks are the tool argument itself (the `project` description says "Reuse from prior context if already known. If not provided, a project selection prompt will be shown.") and the `ado_mcp_project` / `ado_mcp_team` env defaults documented in README, which skip elicitation entirely.

## Other human-in-the-loop mechanisms

- Annotation presets in [src/shared/tool-annotations.ts](https://github.com/microsoft/azure-devops-mcp/blob/65868ea3b843a50b45fdec8babe0ab25dd407002/src/shared/tool-annotations.ts): read-only (`readOnlyHint: true, destructiveHint: false`) vs write (`destructiveHint: true`).
- `-d` / domains flag to load only some tool groups (core, work, work-items, search, test-plans, repositories, wiki, pipelines, advanced-security).
- No confirmation prompts for writes. Elicitation is used only as a picker.

## Notes

- A pure "fill in the missing parameter" pattern: elicitation substitutes for the model guessing a project/team, with live `oneOf` enums built from the API (projects capped at 100, so orgs with more projects cannot pick the rest).
- Cancellation returns a non-error text result, so the model sees "Project selection cancelled." as a normal outcome.
- Write tools (`wit_work_item_write`, link/unlink) are never confirmed. Elicitation only fills the project.
- The README recommends the hosted Remote MCP Server; whether it elicits could not be checked from code.
