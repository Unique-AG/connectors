# Snowflake Cortex AI MCP Server (Snowflake-Labs, deprecated)

| Field | Value |
|---|---|
| Vendor | Snowflake Labs; official-adjacent, now deprecated in favour of Snowflake's managed MCP server |
| Category | infra (enterprise data warehouse) |
| Tier | 2 |
| Source | open (https://github.com/Snowflake-Labs/mcp @ 662cb48) |
| Language / SDK | Python, `fastmcp>=2.14.7,<3` and `mcp[cli]>=1.24.0,<2` (uv.lock: fastmcp 2.14.7, mcp 1.27.1) |
| Hosted endpoint | none for this repo; the README points to Snowflake's managed MCP server (closed, not reviewed) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None. No match for `elicit`, `requestedSchema`, `InputRequired`, `input_requests` or `request_state`. FastMCP 2.14 exposes `ctx.elicit`; it is not used.

## Fallback without client elicitation support

Not applicable. Connection parameters (account, user, password or PAT, key pair, or OAuth token, role, warehouse) come from CLI flags or env vars at startup; the set of enabled services comes from a YAML file.

## Other human-in-the-loop mechanisms

- SQL statement-type allow/deny list, enforced in a FastMCP middleware on `run_snowflake_query` and on any tool whose name starts with `create` or `drop` (`create_object`, `create_or_alter_object`, `drop_object`). Disallowed statements raise `ToolError` "Statement type of X is not allowed. Please review sql statement permissions in configuration file." ([server_utils.py#L9-L46](https://github.com/Snowflake-Labs/mcp/blob/662cb486395d79ab1ad0b3538f933fe6a686ce7c/mcp_server_snowflake/server_utils.py#L9-L46)).
- Deny by default: an empty `sql_statement_permissions` list rejects every statement ([query_manager/tools.py#L104-L106](https://github.com/Snowflake-Labs/mcp/blob/662cb486395d79ab1ad0b3538f933fe6a686ce7c/mcp_server_snowflake/query_manager/tools.py#L104-L106)) and every create/drop ([object_manager/tools.py#L310-L312](https://github.com/Snowflake-Labs/mcp/blob/662cb486395d79ab1ad0b3538f933fe6a686ce7c/mcp_server_snowflake/object_manager/tools.py#L310-L312)); unmapped types need `Unknown: True`.
- Service toggles: `object_manager`, `query_manager`, `semantic_manager` and Cortex services can be switched off in the YAML ([configuration.yaml#L32-L35](https://github.com/Snowflake-Labs/mcp/blob/662cb486395d79ab1ad0b3538f933fe6a686ce7c/services/configuration.yaml#L32-L35)).
- Snowflake RBAC: the configured role bounds what any statement can do.
- No tool annotations (`@server.tool(name=..., description=...)` only), no confirm or dry-run argument; `drop_object` executes immediately when permitted.

## Notes

- The shipped sample `configuration.yaml` allows `Drop`, `Delete`, `TruncateTable`, `Update` etc. as `True` ([configuration.yaml#L36-L52](https://github.com/Snowflake-Labs/mcp/blob/662cb486395d79ab1ad0b3538f933fe6a686ce7c/services/configuration.yaml#L36-L52)), so a copy-paste setup is permissive despite the deny-by-default code.
- Guardrails are entirely operator-time configuration; there is no per-call human confirmation anywhere.
- Deprecated (README banner); last commit May 2026.
