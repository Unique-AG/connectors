# Snowflake-managed MCP server

| Field | Value |
|---|---|
| Vendor | Snowflake; official (Snowflake-managed server object `CREATE MCP SERVER`, distinct from the Snowflake-Labs server in `snowflake-labs.md`) |
| Category | infra (enterprise data warehouse) |
| Tier | 2 |
| Source | closed (account-hosted endpoint) |
| Language / SDK | docs don't say; protocol revision `2025-11-25` |
| Hosted endpoint | `/api/v2/databases/<db>/schemas/<schema>/mcp-servers/<name>` on the account's Snowflake host |
| Uses elicitation | unknown (docs never mention elicitation). The coding-agent approval goes through tool results and a second tool call, not elicitation |
| Mechanism | n/a as documented. Approval round trip via `permission_decisions` tool argument (see below) |
| Evidence type | docs only |

Sources:
- [Snowflake-managed MCP server](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-mcp) ("MCP doc")
- [Coding Agent](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents-coding-agent) ("coding doc")
- [CREATE MCP SERVER](https://docs.snowflake.com/sql-reference/sql/create-mcp-server)

## Elicitation usages

None documented. The MCP doc's Limitations section says the server "does not support the following constructs in the MCP protocol: resources, prompts, roots, notifications, version negotiations, life cycle phases, and sampling". Elicitation is not on that list, and the doc doesn't otherwise mention it.

| Trigger (tool or flow) | Mode | Purpose | What it asks | On decline / cancel | Evidence |
|---|---|---|---|---|---|
| none documented as elicitation | – | – | – | – | – |

There is one documented human-in-the-loop prompt, and it does not use elicitation:

| Trigger | How it asks | Purpose | What it asks | On decline / omission | Evidence |
|---|---|---|---|---|---|
| `CODING_AGENT` / `CORTEX_AGENT_RUN` tool whose sandbox tool (`write`, `edit`, `bash`, `snowflake_sql_execute`) wants to modify state under the default `always_ask` policy | The tool call ends and returns pending permissions. With `background: true`, `ASYNC_AGENT_RUN_STATUS` reports `input_required`. The client re-calls the same tool with `permission_decisions` | confirm-destructive (state-modifying sandbox action) | "Each pending permission has `tool_use_id`, `tool`, `summary`, and `options`." "Clients should take user input" and answer with "one offered option, or `Deny` with an optional `reason`." | "If a pending decision is left out, it is treated as a denial." A deny reason reaches the agent "as the tool's error message" (coding doc) | MCP doc, "Answer a permission prompt", "Run an agent tool in the background"; coding doc, "Sandbox permission policy" |

Other purposes:
- Destructive SQL: the `SYSTEM_EXECUTE_SQL` tool has `read_only`, which "Defaults to `true`" and allows "only read operations (SELECT queries)". The docs mention no confirmation when `read_only` is false.
- Disambiguation / missing parameters: docs don't say. The role is fixed at connect time: "MCP OAuth sessions use the connecting user's `DEFAULT_ROLE` as the primary role".
- Cost confirmation: docs don't say. A `warehouse` can be set per tool, and otherwise "the default warehouse is used".
- Secret entry: docs don't say.

## Fallback without client elicitation support

Not applicable. The coding-agent approval goes through ordinary tool results and arguments, so it needs no client capability. If the call should not stop for approval, the server owner sets `permission_policy` to `always_allow`. That "removes the approval gate: the agent runs any command and modifies any resource its role can reach. Use it only in a trusted automation" (MCP doc). The coding doc's table: `always_ask` = "Always prompt the user for approval before executing state-modifying tools (default)", `always_allow` = "Skip permission checks and execute all tools without user approval".

## Other human-in-the-loop mechanisms

- **Admin-defined tool set.** The server object's YAML specification lists every tool (max 50). Creating it needs `CREATE MCP SERVER`, and changing it needs `OWNERSHIP`.
- **RBAC per tool.** "Access to the MCP Server does not give access to the tools. Permission needs to be granted for each tool" (MCP doc). `tools/list` "omits `CORTEX_AGENT_RUN` tools when the active role does not have `USAGE` on the referenced agent".
- **SQL read-only default.** `SYSTEM_EXECUTE_SQL` has `read_only: true` by default. Snowflake recommends putting direct SQL on "a separate MCP server with a dedicated least-privileged role".
- **Annotations.** Admins can override `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint` for `GENERIC` and `CORTEX_AGENT_RUN` tools. The defaults are `readOnlyHint: false, destructiveHint: true`. "Tool annotations are client-facing hints, not security controls" (MCP doc).
- **Sign-in.** OAuth 2.0 (Snowflake OAuth or External OAuth). The server "doesn't support dynamic client registration", so an admin creates a security integration. `ALLOWED_ROLES_LIST` and `OAUTH_USE_SECONDARY_ROLES = NONE` limit which roles a session gets (MCP doc).

## Notes

- The coding-agent approval loop does the same job as a confirm-destructive elicitation, built from tool results: the call stops, returns `options`, and the client re-calls with a decision. Unanswered prompts count as a denial. The background variant reports the waiting state as `input_required`.
- The approval policy is set by whoever defines the tool or calls `agent:run`. Docs describe no end-user or client-side switch for it.
