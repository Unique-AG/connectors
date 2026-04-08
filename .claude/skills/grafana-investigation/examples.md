# Grafana Investigation Examples

Real-world investigation patterns for connectors and MCP services.

---

## Example 1: SharePoint Connector Sync Failures (QA)

**Scenario:** SharePoint sync reports failing for a tenant on QA.

**Steps:**

1. Discover datasources:
```
list_datasources
  server: "qa-grafana"
  arguments: {}
```

2. Check connector error logs:
```
query_loki_logs
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"sharepoint-connector\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T10:00:00Z",
    "endRfc3339": "2026-04-01T11:00:00Z",
    "limit": 50,
    "direction": "backward"
  }
```

3. Check if upstream ingestion is receiving content:
```
query_loki_logs
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"ingestion\"} |= \"sharepoint\"",
    "startRfc3339": "2026-04-01T10:00:00Z",
    "endRfc3339": "2026-04-01T11:00:00Z",
    "limit": 50
  }
```

4. Check scope-management for permission sync errors:
```
query_loki_logs
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"scope-management\"} |= \"CreateScopeAccesses\" | level = \"error\"",
    "startRfc3339": "2026-04-01T10:00:00Z",
    "endRfc3339": "2026-04-01T11:00:00Z",
    "limit": 50
  }
```

**Key lesson:** SharePoint connector issues often surface as ingestion or scope-management errors upstream. Always check both sides.

---

## Example 2: Confluence Connector Ingestion Slow (Production)

**Scenario:** Confluence content taking too long to appear after sync on a tenant.

**Steps:**

1. Check confluence-connector logs for slow processing:
```
query_loki_logs
  server: "<tenant>-prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"confluence-connector\"} |~ \"completed|duration|elapsed\"",
    "startRfc3339": "2026-04-01T08:00:00Z",
    "endRfc3339": "2026-04-01T10:00:00Z",
    "limit": 50,
    "direction": "backward"
  }
```

2. Check upstream ingestion p95 latency:
```
query_prometheus_histogram
  server: "<tenant>-prod-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "metric": "nestjs_http_server_request_duration_ms",
    "percentile": 0.95,
    "labels": "{app=\"node_ingestion\", operationName=\"Content\"}",
    "startTime": "now-2h",
    "endTime": "now",
    "stepSeconds": 60
  }
```

3. Check ingestion-worker for queued work:
```
query_loki_logs
  server: "<tenant>-prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"ingestion-worker\"} |= \"confluence\"",
    "startRfc3339": "2026-04-01T08:00:00Z",
    "endRfc3339": "2026-04-01T10:00:00Z",
    "limit": 50
  }
```

4. Check container resources — connector might be memory-constrained:
```
query_prometheus
  server: "<tenant>-prod-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "container_memory_working_set_bytes{container=\"confluence-connector\"} / 1024 / 1024",
    "queryType": "range",
    "startTime": "now-2h",
    "endTime": "now",
    "stepSeconds": 60
  }
```

**Key lesson:** Slow ingestion can be the connector, the upstream ingestion service, or the ingestion worker. Check all three and correlate timestamps.

---

## Example 3: Outlook MCP Tool Failures (UAT)

**Scenario:** Users report Outlook MCP tools failing in chat on UAT.

**Steps:**

1. Check MCP server logs:
```
query_loki_logs
  server: "uat1-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"mcp-server-outlook\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T14:00:00Z",
    "endRfc3339": "2026-04-01T15:00:00Z",
    "limit": 50,
    "direction": "backward"
  }
```

2. Check mcp-hub for dispatch errors:
```
query_loki_logs
  server: "uat1-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"mcp-hub\"} |= \"outlook\" | level = \"error\"",
    "startRfc3339": "2026-04-01T14:00:00Z",
    "endRfc3339": "2026-04-01T15:00:00Z",
    "limit": 50
  }
```

3. Check chat service for MCP invocation errors:
```
query_loki_logs
  server: "uat1-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"chat\"} |= \"mcp\" | level = \"error\"",
    "startRfc3339": "2026-04-01T14:00:00Z",
    "endRfc3339": "2026-04-01T15:00:00Z",
    "limit": 50
  }
```

4. Check if the MCP pod is healthy:
```
query_prometheus
  server: "uat1-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "container_cpu_usage_seconds_total{container=\"mcp-server-outlook\"}",
    "queryType": "range",
    "startTime": "now-1h",
    "endTime": "now",
    "stepSeconds": 60
  }
```

**Key lesson:** MCP tool failures involve three layers: chat -> mcp-hub -> mcp-server. Check all three to isolate where the failure occurs.

---

## Example 4: Teams MCP GraphQL Error Rate Spike (Production)

**Scenario:** Alert fires for Teams MCP GraphQL error rate > 1%.

**Steps:**

1. Check existing dashboard for the alert context:
```
search_dashboards
  server: "prod-grafana"
  arguments: { "query": "teams" }
```

2. Extract queries from the dashboard:
```
get_dashboard_panel_queries
  server: "prod-grafana"
  arguments: { "uid": "<teams-dashboard-uid>" }
```

3. Check error logs with details:
```
query_loki_logs
  server: "prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"teams-mcp\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T12:00:00Z",
    "endRfc3339": "2026-04-01T12:30:00Z",
    "limit": 100,
    "direction": "backward"
  }
```

4. Check if it correlates with upstream Unique API errors:
```
query_loki_logs
  server: "prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"unique-api\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T12:00:00Z",
    "endRfc3339": "2026-04-01T12:30:00Z",
    "limit": 50
  }
```

**Key lesson:** Teams MCP has PrometheusRule alerts for GraphQL errors and Unique API errors. Check the alert definition first to understand thresholds, then investigate root cause.

---

## Example 5: Cross-Tenant Connector Resource Usage (Multi-Prod)

**Scenario:** Need to compare SharePoint connector memory usage across tenants before adjusting resource limits.

**Steps:**

1. Run the same query across tenant Grafana servers in parallel:
```
query_prometheus
  server: "<tenant>-prod-grafana"    (repeat for each tenant)
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "max(max_over_time(container_memory_working_set_bytes{container=\"sharepoint-connector\"}[7d])) / 1024 / 1024",
    "queryType": "instant",
    "startTime": "now"
  }
```

2. Also get average:
```
  "expr": "avg(avg_over_time(container_memory_working_set_bytes{container=\"sharepoint-connector\"}[7d])) / 1024 / 1024"
```

3. Aggregate results into a comparison table:
```
| Tenant   | Avg (MiB) | Max (MiB) |
|----------|-----------|-----------|
| tenant-a | 450       | 780       |
| tenant-b | 320       | 550       |
| ...      | ...       | ...       |
```

**Key lesson:** 30d averages hide spikes. Always include `max_over_time` with a shorter window (7d) to show the real peak.

---

## Example 6: Before/After Validation for Connector PR (QA)

**Scenario:** PR merged that optimizes SharePoint scanning — validate improvement.

**Steps:**

1. Get merge timestamp:
```bash
gh pr view 450 --repo Unique-AG/connectors --json mergedAt --jq '.mergedAt'
```

2. Check connector CPU usage before vs after:
```
query_prometheus
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "sum(rate(container_cpu_usage_seconds_total{container=\"sharepoint-connector\"}[5m])) by (pod)",
    "queryType": "range",
    "startTime": "<merge - 2d>",
    "endTime": "<merge>",
    "stepSeconds": 300
  }
```

3. Same query for after window:
```
  "startTime": "<merge>",
  "endTime": "now"
```

4. Also compare memory:
```
  "expr": "container_memory_working_set_bytes{container=\"sharepoint-connector\"} / 1024 / 1024"
```

**Key lesson:** For connector performance validation, CPU and memory are the primary indicators since connectors don't expose NestJS HTTP histograms the same way platform services do.

---

## Example 7: Outlook Semantic MCP Sync Monitoring

**Scenario:** Full sync running on outlook-semantic-mcp — monitor progress and detect stalls.

**Steps:**

1. Watch sync progress logs:
```
query_loki_logs
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"outlook-semantic-mcp\"} |~ \"sync|checkpoint|resume|completed\"",
    "startRfc3339": "2026-04-01T06:00:00Z",
    "endRfc3339": "2026-04-01T12:00:00Z",
    "limit": 100,
    "direction": "forward"
  }
```

2. Check for errors during sync:
```
query_loki_logs
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"outlook-semantic-mcp\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T06:00:00Z",
    "endRfc3339": "2026-04-01T12:00:00Z",
    "limit": 50
  }
```

3. Monitor resource consumption during sync:
```
query_prometheus
  server: "qa-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "sum(rate(container_cpu_usage_seconds_total{container=\"outlook-semantic-mcp\"}[2m])) by (pod)",
    "queryType": "range",
    "startTime": "2026-04-01T06:00:00Z",
    "endTime": "2026-04-01T12:00:00Z",
    "stepSeconds": 60
  }
```

**Key lesson:** Outlook semantic MCP uses checkpoint-based full sync with resume. Monitor for stalls by checking if new log entries stop appearing.

---

## Example 8: FactSet MCP Data Query Issues

**Scenario:** FactSet MCP returning errors when users invoke it from chat.

**Steps:**

1. Check FactSet MCP server logs:
```
query_loki_logs
  server: "prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"mcp-server-factset\"} | level = \"error\"",
    "startRfc3339": "2026-04-01T09:00:00Z",
    "endRfc3339": "2026-04-01T10:00:00Z",
    "limit": 50,
    "direction": "backward"
  }
```

2. Check mcp-hub dispatch:
```
query_loki_logs
  server: "prod-grafana"
  arguments: {
    "datasourceUid": "<loki-uid>",
    "logql": "{app=\"mcp-hub\"} |= \"factset\"",
    "startRfc3339": "2026-04-01T09:00:00Z",
    "endRfc3339": "2026-04-01T10:00:00Z",
    "limit": 50
  }
```

3. Check pod health:
```
query_prometheus
  server: "prod-grafana"
  arguments: {
    "datasourceUid": "prometheus",
    "expr": "up{job=~\".*factset.*\"}",
    "queryType": "instant",
    "startTime": "now"
  }
```

**Key lesson:** FactSet MCP depends on external FactSet APIs. Errors may be upstream (FactSet service) rather than internal. Check response codes in logs to distinguish.
