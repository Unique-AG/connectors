# Grafana MCP Tool Reference

Complete parameter reference for all 50 Grafana MCP tools. Organized by category.

## Datasources

### list_datasources
List configured datasources to discover UIDs.
- `type` — filter by type (e.g. `prometheus`, `loki`, `tempo`)
- `limit` — max 100, default 50
- `offset` — default 0

### get_datasource
Full datasource model.
- `uid` — preferred identifier
- `name` — fallback if uid unknown; uid wins if both provided

## Dashboards and Folders

### search_dashboards
Text search dashboards by title/metadata.
- `query` — search string
- `limit` — max 100, default 50
- `page` — default 1

### search_folders
Search folders by query string.
- `query` — search string

### get_dashboard_by_uid
**Warning: returns very large JSON.** Use summary or property tools instead.
- `uid` — required

### get_dashboard_summary
Compact overview: panels, variables, metadata.
- `uid` — required

### get_dashboard_property
Efficient JSONPath slices of a dashboard.
- `uid` — required
- `jsonPath` — e.g. `$.title`, `$.panels[*].targets[*].expr`

### get_dashboard_panel_queries
Extract panel queries and datasource info.
- `uid` — required
- `panelId` — optional, specific panel
- `variables` — map of template variable values for `processedQuery`

### update_dashboard
Create or update dashboards. Full JSON or patch mode.
- Full: `dashboard` (complete JSON object)
- Patch: `uid` + `operations` array (`op`: replace/add/remove, `path`, `value`)
- Optional: `folderUid`, `message`, `overwrite`, `userId`

### create_folder
- `title` — required
- `uid` — optional
- `parentUid` — optional

## Rendering and Navigation

### get_panel_image
Render panel or dashboard as PNG (base64). Requires Image Renderer plugin.
- `dashboardUid` — required
- `panelId` — optional (omit for full dashboard)
- `timeRange` — `{ "from": "...", "to": "..." }`
- `variables` — template variable map
- `width`, `height`, `scale` (1-3), `theme` (light/dark), `timeout` (seconds)

### generate_deeplink
Create URLs for dashboards, panels, or Explore.
- `resourceType` — required: `dashboard` | `panel` | `explore`
- For dashboard/panel: `dashboardUid`; panel also needs `panelId`
- For explore: `datasourceUid`
- `timeRange` — optional `{ "from", "to" }`
- `queryParams` — optional key-value map

## Annotations

### create_annotation
- `text` — required (unless graphite format)
- Optional: `dashboardUID`, `panelId`, `time`, `timeEnd`, `tags`, `data`
- Graphite format: `format: "graphite"`, `what`, `when`

### get_annotations
- `DashboardUID`, `PanelID`, `From`/`To` (epoch ms), `Tags`, `MatchAny`, `Limit`, `Type`, `AlertUID`, `UserID`

### get_annotation_tags
- `tag` — optional filter
- `limit` — default "100"

### update_annotation
- `id` — required (numeric)
- Partial: `text`, `tags`, `time`, `timeEnd`, `data`

## Prometheus (Metrics)

### list_prometheus_metric_names
- `datasourceUid` — required
- `regex` — filter pattern
- `limit` — default 10
- `page` — default 1

### list_prometheus_metric_metadata
Experimental metadata API.
- `datasourceUid` — required
- `metric` — optional filter
- `limit` — default 10
- `limitPerMetric` — optional

### list_prometheus_label_names
- `datasourceUid` — required
- `matches` — array of `{ filters: [{ name, value, type }] }`, type: `=`, `!=`, `=~`, `!~`
- `startRfc3339`, `endRfc3339` — optional
- `limit` — default 100

### list_prometheus_label_values
- `datasourceUid` — required
- `labelName` — required
- `matches`, `startRfc3339`, `endRfc3339`, `limit` — same as label names

### query_prometheus
**Required:** `datasourceUid`, `expr`, `startTime`
- `queryType` — `range` or `instant`
- For range: `endTime`, `stepSeconds`
- Times: RFC3339 or relative (`now`, `now-1h`)

### query_prometheus_histogram
Convenience for `histogram_quantile`.
- **Required:** `datasourceUid`, `metric` (base name without `_bucket`), `percentile`
- Optional: `labels`, `rateInterval` (default 5m), `startTime`, `endTime`, `stepSeconds`

## Loki (Logs)

### list_loki_label_names
- `datasourceUid` — required
- `startRfc3339`, `endRfc3339` — optional (default last hour)

### list_loki_label_values
- `datasourceUid` — required
- `labelName` — required
- `startRfc3339`, `endRfc3339` — optional

### query_loki_stats
Stream stats for a selector (no line filters).
- `datasourceUid` — required
- `logql` — **stream selector only** (e.g. `{app="sharepoint-connector"}`)
- `startRfc3339`, `endRfc3339` — optional

### query_loki_patterns
Pattern detection on log streams.
- `datasourceUid` — required
- `logql` — **stream selector only**
- `startRfc3339`, `endRfc3339`, `step` — optional

### query_loki_logs
Full LogQL execution.
- `datasourceUid` — required
- `logql` — required
- `startRfc3339`, `endRfc3339` — optional
- `limit` — max 100, default 10
- `direction` — `forward` or `backward`
- `queryType` — `range` or `instant` (use instant for metric queries like `count_over_time`)
- `stepSeconds` — for range metric queries

## Pyroscope (Profiling)

**Note:** Pyroscope tools use **snake_case** parameters (`data_source_uid`, `start_rfc_3339`).

### list_pyroscope_profile_types
- `data_source_uid` — required
- `start_rfc_3339`, `end_rfc_3339` — optional

### list_pyroscope_label_names
- `data_source_uid` — required
- `matchers` — optional (string in Prom selector style, e.g. `{service_name="foo"}`)
- `start_rfc_3339`, `end_rfc_3339` — optional

### list_pyroscope_label_values
- `data_source_uid` — required
- `name` — label name, required
- `matchers`, `start_rfc_3339`, `end_rfc_3339` — optional

### fetch_pyroscope_profile
Returns profile in DOT format.
- `data_source_uid` — required
- `profile_type` — required
- `matchers`, `start_rfc_3339`, `end_rfc_3339` — optional
- `max_node_depth` — default 100, -1 for unbounded

## Alerting

### alerting_manage_rules
- **Required:** `operation` — `list` | `get` | `versions` | `create` | `update` | `delete`
- List: `folder_uid` or `search_folder`, `label_selectors`, `datasource_uid`, `rule_limit`, `limit_alerts`
- Get/versions/update/delete: `rule_uid`
- Create/update: `title`, `folder_uid`, `rule_group`, `org_id`, `for`, `condition`, `data` (queries array), `no_data_state`, `exec_err_state`, labels, annotations

### alerting_manage_routing
Read-only routing information.
- **Required:** `operation` — `get_notification_policies` | `get_contact_points` | `get_contact_point` | `get_time_intervals` | `get_time_interval`
- Optional: `datasource_uid`, `limit`, `name`, `contact_point_title`, `time_interval_name`

## Incidents

### list_incidents
- `status` — `active` or `resolved`
- `drill` — boolean
- `limit` — default 10

### get_incident
- `id` — required

### create_incident
**Caution: may trigger wide notifications.** Confirm with user first.
- `title`, `severity`, `roomPrefix` — required
- Optional: `status`, `isDrill`, `labels`, `attachUrl`, `attachCaption`

### add_activity_to_incident
- `incidentId` — required
- `body` — required
- `eventTime` — optional

## OnCall

### list_alert_groups
- Filters: `id`, `routeId`, `integrationId`, `state`, `teamId`, `name`, `labels` (array of `key:value`), `startedAt` (`start_end` ISO range), `page`

### get_alert_group
- `alertGroupId` — required

### list_oncall_schedules
- `teamId`, `scheduleId`, `page`

### get_oncall_shift
- `shiftId` — required

### get_current_oncall_users
- `scheduleId` — required

### list_oncall_teams
- `page`

### list_oncall_users
- `page`, `userId`, `username`

## Sift (Automated Analysis)

### list_sift_investigations
- `limit` — default 10

### get_sift_investigation
- `id` — UUID string

### get_sift_analysis
- `investigationId` — UUID
- `analysisId` — UUID

### find_error_pattern_logs
Loki error-pattern analysis vs baseline.
- **Required:** `name`, `labels` (object)
- Optional: `start`, `end` (defaults ~30min window)

### find_slow_requests
Tempo-based slow-request analysis. **Requires Tempo datasource.**
- **Required:** `name`, `labels` (object)
- Optional: `start`, `end`

## Assertions

### get_assertions
- **Required:** `startTime`, `endTime` (RFC3339)
- Optional: `entityType`, `entityName`, `env`, `site`, `namespace`

## Parameter Naming Conventions

| Context | Pattern | Example |
|---------|---------|---------|
| Prometheus/Loki | camelCase | `datasourceUid`, `startRfc3339` |
| Pyroscope | snake_case | `data_source_uid`, `start_rfc_3339` |
| Alerting rules | snake_case | `datasource_uid`, `folder_uid` |
| Annotations | PascalCase | `DashboardUID`, `PanelID` |
| Time formats | Mixed | RFC3339 strings, `now-1h` relative, epoch ms (annotations) |
