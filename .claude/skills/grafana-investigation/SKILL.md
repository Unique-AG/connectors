---
name: grafana-investigation
description: >-
  Investigate production issues, diagnose performance problems, and analyze
  service health using Grafana MCP servers (Prometheus, Loki, Tempo, Sift).
  Use when the user asks to check logs, investigate errors, analyze latency,
  monitor resources, query metrics, debug slowness, check alerts, or
  investigate any environment (QA, UAT, prod, tenant-specific).
---

# Grafana Investigation

Investigate service health, diagnose errors, and analyze performance across Unique platform environments using Grafana MCP servers. Tailored for the connectors monorepo services and the upstream Unique platform services they depend on.

## Enhanced Details (Private Monorepo)

If you have filesystem access to the Unique monorepo, check for `../monorepo/.claude/skills/grafana-investigation/SKILL.md` (relative to this repo root). If it exists, read it — it contains internal details not included here:

- Grafana URL patterns and DNS hostnames
- Tenant environment slugs (all production single-tenant names)
- Loki datasource UIDs per environment
- Complete namespace-to-service mapping
- Full upstream service label table (including web apps and Python AI services)
- Additional Prometheus metrics (chat LLM, ingestion embeddings, Node.js process, Elasticsearch)

Use those concrete values instead of the generic placeholders in this file. If the monorepo is not available, this skill is fully self-contained — proceed with discovery steps below.

## Prerequisites

1. Install `uv` (Python package manager — provides `uvx`)
2. Be connected to the internal VPN/tailnet (Grafana URLs use internal DNS)
3. Add Grafana MCP servers to your Claude Code MCP config (see setup below)

### MCP Server Setup

Add Grafana MCP servers to your Claude Code settings (project `.claude/settings.json` or user `~/.claude/settings.json`) under `mcpServers`:

```json
"<env>-grafana": {
  "command": "uvx",
  "args": ["mcp-grafana"],
  "env": {
    "GRAFANA_URL": "<your-grafana-url-for-this-environment>"
  }
}
```

Ask your team for the Grafana URLs for each environment. Add one entry per environment you need to query.

Each configured server becomes available as MCP tools with the server name prefix (e.g. `qa-grafana` key gives tools like `mcp__qa-grafana__list_datasources`).

## Environment Servers

| MCP Server Key | Environment | Use Case |
|----------------|-------------|----------|
| `qa-grafana` | QA | Development testing, pre-merge validation |
| `uat-grafana` | UAT | Pre-production validation |
| `prod-grafana` | Production (shared) | Multi-tenant production |
| `{tenant}-prod-grafana` | Tenant-specific prod | One per single-tenant deployment |

**Choosing the right server:** Match the environment where the issue was reported. For multi-tenant investigations, run parallel queries across tenant servers.

## Quick Reference — Connectors Service Names

### Connector Services (this repo)

All services emit Prometheus metrics via OpenTelemetry (port **51346** for most services; **51350** for `confluence-connector`).

| Service directory | Helm chart name | Grafana dashboard folder | Loki `app` label (verify) |
|-------------------|-----------------|--------------------------|---------------------------|
| `services/sharepoint-connector` | `sharepoint-connector` | `connectors` | `sharepoint-connector` |
| `services/confluence-connector` | `confluence-connector` | `connectors` | `confluence-connector` |
| `services/outlook-mcp` | `mcp-server-outlook` | `mcp-servers` | `mcp-server-outlook` |
| `services/outlook-semantic-mcp` | `outlook-semantic-mcp` | `mcp-servers` | `outlook-semantic-mcp` |
| `services/teams-mcp` | `teams-mcp` | `mcp-servers` | `teams-mcp` |
| `services/factset-mcp` | `mcp-server-factset` | `mcp-servers` | `mcp-server-factset` |

**Important:** Loki `app` labels typically match the Helm chart name, but always verify with `list_loki_label_values` since naming can vary per cluster.

### Upstream Unique Platform Services (monorepo)

Connectors interact heavily with these services. Use the Prometheus/Loki labels below when correlating issues.

| Service | Prometheus `app` label | Loki `app` label | What it does |
|---------|----------------------|-----------------|--------------|
| `node-ingestion` | `node_ingestion` | `ingestion` | Content ingestion (connectors push content here) |
| `node-ingestion-worker` | `node_ingestion_worker` | `ingestion-worker` | Async ingestion processing |
| `node-scope-management` | `node_scope_management` | `scope-management` | Scope/permission management |
| `node-chat` | `node_chat` | `chat` | Chat service (MCP tools are called from here) |
| `gatekeeper` | `gatekeeper` | `gatekeeper` | Auth gateway |
| `unique-api` | `unique_api` | `unique-api` | API gateway |
| `mcp-hub` | `mcp_hub` | `mcp-hub` | MCP tool orchestration |

**Label naming difference:** Prometheus uses underscores (`node_ingestion`), Loki uses hyphens (`ingestion`). Always verify with `list_*_label_values`.

### Common Namespaces

Namespaces are **cluster-specific** and vary across environments. Always discover them:
```
list_loki_label_values
  arguments: { "datasourceUid": "<loki-uid>", "labelName": "namespace" }
```

Connector and MCP services may deploy to their own namespaces.

### Common Prometheus Metrics

**OpenTelemetry metrics (all connector services):**
Connectors use the `@unique-ag/instrumentation` package with OpenTelemetry. Metric names vary by service — discover with:
```
list_prometheus_metric_names
  arguments: { "datasourceUid": "prometheus", "regex": ".*sharepoint.*|.*confluence.*|.*outlook.*|.*teams.*|.*factset.*" }
```

**NestJS HTTP metrics (upstream platform services):**
- `nestjs_http_server_request_duration_ms` (histogram — use for p95/p99)
- `nestjs_http_server_requests_total` / `nestjs_http_server_responses_total`
- `nestjs_http_server_responses_error_total`

**Kubernetes container metrics (all services):**
- `container_cpu_usage_seconds_total{container="...", namespace="..."}`
- `container_memory_working_set_bytes{container="...", namespace="..."}`

**Elasticsearch (used by ingestion):**
- `elasticsearch_cluster_health_status{cluster="elasticsearch-ingestion"}`
- `elasticsearch_cluster_health_unassigned_shards`

### Common Loki Labels

| Label | What it filters | Example values |
|-------|----------------|----------------|
| `app` | Service name (Helm chart name) | `sharepoint-connector`, `mcp-server-outlook`, `ingestion` |
| `namespace` | Kubernetes namespace | Discover with `list_loki_label_values` |
| `context` | NestJS logger class name | `SharepointSynchronizationService`, `ConfluenceSynchronizationService` |
| `level` | Log level | `error`, `warn`, `info`, `debug` |
| `container` | Container name in pod | `sharepoint-connector`, `outlook-mcp` |

### Common GraphQL Operation Names

Used as `operationName` label when connectors call upstream services:

**Ingestion:** `Content`, `PaginatedContent`, `CreateScopeAccesses`, `DeleteScopeAccesses`, `BulkMove`
**Scopes:** `AllScopesIdsByCompany`

## Investigation Workflow

Always follow this sequence. Do NOT skip discovery steps — label names and datasource UIDs vary across environments.

### Step 1: Discover Datasources

```
list_datasources
  server: "<env>-grafana"
  arguments: {}
```

Record the `uid` values — they vary per environment. Always discover them rather than hardcoding.

### Step 2: Discover Labels and Metrics

Before writing any PromQL or LogQL, discover what actually exists.

**For Prometheus:**
```
list_prometheus_metric_names   → regex: ".*sharepoint.*", ".*confluence.*", ".*nestjs.*"
list_prometheus_label_values   → labelName: "app" or "job" or "container"
```

**For Loki:**
```
list_loki_label_names          → see available labels
list_loki_label_values         → labelName: "app", then "namespace", "context"
```

**Why this matters:** Label values use inconsistent naming across services and environments. Always verify before querying.

### Step 3: Search Existing Dashboards

Each connector service has a Grafana dashboard. Search for it:

```
search_dashboards
  arguments: { "query": "sharepoint" }
```

Use `get_dashboard_summary` or `get_dashboard_panel_queries` to extract useful queries from existing dashboards rather than writing PromQL from scratch.

### Step 4: Query Metrics and Logs

Choose the right tool based on what you need. See sections below.

---

## Prometheus Queries (Metrics)

### query_prometheus

```
query_prometheus
  server: "<env>-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "<PromQL>",
    "queryType": "range",
    "startTime": "now-1h",
    "endTime": "now",
    "stepSeconds": 60
  }
```

### query_prometheus_histogram

Convenience tool for percentile calculations:

```
query_prometheus_histogram
  arguments: {
    "datasourceUid": "prometheus",
    "metric": "nestjs_http_server_request_duration_ms",
    "percentile": 0.95,
    "labels": "{app=\"node_ingestion\"}",
    "rateInterval": "5m",
    "startTime": "now-1h",
    "endTime": "now",
    "stepSeconds": 300
  }
```

### Common PromQL Patterns

**Container CPU (connector service):**
```promql
sum(rate(container_cpu_usage_seconds_total{container="sharepoint-connector"}[5m])) by (pod)
```

**Container memory (bytes to MiB):**
```promql
container_memory_working_set_bytes{container="confluence-connector"} / 1024 / 1024
```

**Upstream ingestion latency (when investigating slow connector syncs):**
```promql
histogram_quantile(0.95, sum(rate(nestjs_http_server_request_duration_ms_bucket{app="node_ingestion", operationName="Content"}[5m])) by (le))
```

**Upstream scope-management latency:**
```promql
histogram_quantile(0.95, sum(rate(nestjs_http_server_request_duration_ms_bucket{app="node_scope_management", operationName="CreateScopeAccesses"}[5m])) by (le))
```

---

## Loki Queries (Logs)

### query_loki_logs

```
query_loki_logs
  server: "<env>-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"sharepoint-connector\"} |= \"error\"",
    "startRfc3339": "2026-04-01T13:00:00Z",
    "endRfc3339": "2026-04-01T14:00:00Z",
    "limit": 50,
    "direction": "backward"
  }
```

### Common LogQL Patterns

**Connector service errors:**
```logql
{app="sharepoint-connector"} | level = "error"
```

**Confluence connector sync issues:**
```logql
{app="confluence-connector"} |= "failed" | level = "error"
```

**MCP server errors (Outlook, Teams):**
```logql
{app="mcp-server-outlook"} | level = "error"
```

```logql
{app="teams-mcp"} | level = "error"
```

**Correlate connector with upstream ingestion:**
```logql
{app="ingestion"} |= "sharepoint" | level = "error"
```

**Search by NestJS context (class name):**
```logql
{app="sharepoint-connector", context="SharepointScannerService"}
```

**Count occurrences (metric query):**
```logql
sum(count_over_time({app="confluence-connector"} |= "ingestion" [24h]))
```
Use `queryType: "instant"` for metric LogQL.

**Search by trace ID:**
```logql
{namespace="<connector-namespace>"} |= "a1cfdb..."
```
Narrow namespace first — `{} |= "traceId"` is extremely expensive.

### LogQL Pitfalls

1. **Wide queries cause 502/timeout:** Always narrow with `app`, `namespace`, or `context` labels AND short time windows (15min ideally)
2. **NestJS colored/ANSI logs break `| json`:** Use `|=` (contains) or `|~` (regex) line filters instead
3. **`limit` max is 100** per the MCP tool — paginate with time windows if you need more
4. **Label discovery first:** Always run `list_loki_label_values` for `app` before guessing

---

## Tempo / Traces

`find_slow_requests` requires Tempo and may not be available on all environments.

**When Tempo is available:**
```
find_slow_requests
  arguments: {
    "name": "sharepoint-connector slow requests",
    "labels": { "app": "sharepoint-connector" },
    "start": "2026-04-01T13:00:00Z",
    "end": "2026-04-01T14:00:00Z"
  }
```

**When Tempo is unavailable — fallback:**
1. Use `generate_deeplink` to create an Explore URL the user can open manually
2. Query Loki for logs containing the trace ID (narrow by namespace)
3. Use PromQL histogram percentiles as a proxy for latency

---

## Connector-Specific Investigation Patterns

### SharePoint Connector Sync Issues

1. Check connector logs for sync errors:
```logql
{app="sharepoint-connector"} |= "sync" | level = "error"
```

2. Check if upstream ingestion is slow/failing:
```logql
{app="ingestion"} |= "sharepoint" | level = "error"
```

3. Check scope-management for permission sync:
```logql
{app="scope-management"} |= "CreateScopeAccesses" | level = "error"
```

### Confluence Connector Ingestion

1. Check connector processing:
```logql
{app="confluence-connector"} | level = "error"
```

2. Correlate with ingestion worker:
```logql
{app="ingestion-worker"} |= "confluence"
```

### MCP Server Issues (Outlook, Teams, FactSet)

MCP servers are called from `mcp-hub` in the platform. Investigate both sides:

1. Check MCP server logs:
```logql
{app="mcp-server-outlook"} | level = "error"
```

2. Check mcp-hub for dispatch errors:
```logql
{app="mcp-hub"} |= "outlook" | level = "error"
```

3. Check chat service (MCP tools are invoked from chat):
```logql
{app="chat"} |= "mcp" | level = "error"
```

---

## Multi-Tenant Investigation

For cross-tenant analysis, run parallel queries across Grafana servers:

1. Call `list_datasources` on each server to get UIDs
2. Run the same query against each server in parallel
3. Aggregate results into a comparison table

---

## Before/After Performance Comparison

To validate a code change after a PR merge:

1. Get the merge timestamp: `gh pr view <number> --json mergedAt`
2. Query the same metric for a window before and after the merge time
3. Compare p95/p99 latencies or throughput

```
Before: startTime = merge - 2d, endTime = merge
After:  startTime = merge, endTime = now
```

---

## Dashboard and Panel Tools

| Tool | When to Use |
|------|-------------|
| `search_dashboards` | Find relevant dashboards by keyword |
| `get_dashboard_summary` | Quick overview of panels and variables |
| `get_dashboard_panel_queries` | Extract PromQL/LogQL from existing panels |
| `get_dashboard_property` | Efficient JSONPath slice |
| `get_panel_image` | Render a panel as PNG for evidence/sharing |

Avoid `get_dashboard_by_uid` — returns very large JSON. Use summary or property tools instead.

---

## Alerting and Incidents

**Check firing alerts:**
```
list_alert_groups
  arguments: { "state": "firing" }
```

**Check active incidents:**
```
list_incidents
  arguments: { "status": "active" }
```

**Caution:** `create_incident` may trigger wide notifications — always confirm with the user first.

---

## Sift Investigations

Automated root-cause analysis when available:

```
find_error_pattern_logs
  arguments: {
    "name": "sharepoint-connector errors",
    "labels": { "app": "sharepoint-connector" }
  }
```

---

## Common Pitfalls Reference

| Pitfall | Solution |
|---------|----------|
| Wrong `app` label for connector | Verify with `list_loki_label_values` — may be chart name or directory name |
| Prometheus underscore vs Loki hyphen | Platform services differ: `node_ingestion` (Prom) vs `ingestion` (Loki) |
| Loki 502 on wide queries | Narrow time window (15min), add label selectors |
| `| json` fails on colored logs | Use `|=` or `|~` line filters |
| Connector issue is actually upstream | Always check both connector AND platform service logs |
| `find_slow_requests` unavailable | Tempo not deployed; use PromQL histograms + Loki |
| Tool param naming varies | Pyroscope uses snake_case, others camelCase |
| Dashboard JSON too large | Use `get_dashboard_summary` or `get_dashboard_property` |

## Additional Resources

- For end-to-end investigation walkthroughs, see [examples.md](examples.md)
- For complete tool schemas and parameter details, see [tool-reference.md](tool-reference.md)
