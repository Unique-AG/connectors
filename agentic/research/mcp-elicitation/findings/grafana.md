# Grafana MCP (mcp-grafana)

| Field | Value |
|---|---|
| Vendor | Grafana Labs; official |
| Category | infra |
| Tier | 3 |
| Source | open (https://github.com/grafana/mcp-grafana @ fa5fd85) |
| Language / SDK | Go, `github.com/modelcontextprotocol/go-sdk` v1.8.0 (go.mod) |
| Hosted endpoint | none in repo (self-run stdio / SSE / streamable HTTP) |
| Uses elicitation | no |
| Mechanism | n/a |
| Evidence type | code |

## Elicitation usages

None in the server. The only `elicit` hits are inside the bundled MCP Apps UI JavaScript (`ui/*/dist/*.html`, minified SDK code), not Go server code. The go-sdk v1.8.0 in use supports elicitation, but no tool calls it.

## Fallback without client elicitation support

Not applicable.

## Other human-in-the-loop mechanisms

Permalink base: `https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/`

Grafana does through the model what an elicitation would otherwise do. A first call returns instructions plus data, and the model must ask the user and call again with a flag or value.

- **`create_datasource` / `update_datasource`, two-step "schemaReviewed" (fill-missing-param by text).** A first call without `schemaReviewed=true` returns the plugin's field schema plus: "You MUST ask the user for the value of every required field (required=true) before calling create_datasource again. Do NOT infer, guess, or use default values for required fields without explicit confirmation from the user..." The second call carries the values and `schemaReviewed=true` ([tools/datasource_schemas/datasource_schemas_utils.go#L262](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/tools/datasource_schemas/datasource_schemas_utils.go#L262), [tools/datasources.go#L127](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/tools/datasources.go#L127)).
- **Secrets are sent to the UI.** "Secrets (passwords, tokens, and other secureJsonData) cannot be set here — direct the user to the Grafana UI for those, and if the user shares a credential in the conversation, remind them to rotate it." ([datasource_schemas_utils.go#L267](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/tools/datasource_schemas/datasource_schemas_utils.go#L267)). This is the job URL-mode elicitation is meant for, done as plain text.
- **`install_plugin` without `version` (disambiguate / confirm).** Returns `confirmationRequired: true` and the latest catalog version: "Ask the user whether to install this version or a specific one, then call install_plugin again with the chosen version." Nothing is installed on the first call ([tools/plugins.go#L206](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/tools/plugins.go#L206)).
- **Write gating flags.** `--disable-write` removes create/update tools. `--enable-write-tools=<names>` and `--enable-query` opt specific tools back in. `--enabled-tools` / `--disable-<category>` act as category allowlists ([cmd/mcp-grafana/main.go#L200-L203](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/cmd/mcp-grafana/main.go#L200-L203)).
- **Annotations.** `readOnlyHint` / `destructiveHint` / `openWorldHint` on tools. `destructiveHint(true)` on raw query tools (`query_sql`, `query_influxdb`, `query_datasource`), silences, dashboards, snapshots, OnCall, incidents and datasources, e.g. [tools/sql_tools.go#L304](https://github.com/grafana/mcp-grafana/blob/fa5fd85a3c4b54f0512c2342ebf87f6287be81d8/tools/sql_tools.go#L304).
- `RequiresPermissions(...)` metadata on tools records which Grafana RBAC permissions a tool needs. I did not trace whether it filters the tool list.

## Notes

- `schemaReviewed` is a boolean the model sets itself, so the "ask the user" step is advisory and nothing enforces it. A form elicitation over the same field schema would enforce it. This server is a clear candidate for one.
- Dashboard writes refuse a possibly lossy v2 write rather than ask ("refusing a possibly lossy write"). The tool fails closed instead of confirming.
