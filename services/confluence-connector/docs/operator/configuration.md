<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## Configuration Overview

The Confluence Connector uses a **YAML-based tenant configuration file** for all settings. The configuration file path is specified via the `TENANT_CONFIG_PATH_PATTERN` environment variable.

## Environment Variables

The following environment variables control application-level behavior. They are set outside the tenant configuration YAML (typically in Helm `connector.env`).

| Variable | Default | Description |
|---|---|---|
| `NODE_ENV` | `production` | Environment mode (`development`, `production`, `test`) |
| `PORT` | `51349` | HTTP port the application binds to |
| `LOG_LEVEL` | `info` | Log verbosity: `fatal`, `error`, `warn`, `info`, `debug`, `trace`, `silent`. See [Logging](#logging) |
| `LOGS_DIAGNOSTICS_DATA_POLICY` | `conceal` | Controls whether diagnostic data (emails, usernames, IDs) is logged in full (`disclose`) or partially masked (`conceal`). See [Logging](#diagnostics-data-policy) |
| `TENANT_CONFIG_PATH_PATTERN` | -- (required; Helm chart sets `/app/tenant-configs/*-tenant-config.yaml`) | Glob pattern to tenant configuration YAML files |
| `OTEL_METRICS_EXPORTER` | -- | OpenTelemetry metrics exporter (e.g., `prometheus`). See [Metrics](#metrics) |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | -- | Prometheus exporter bind host |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | -- | Prometheus exporter bind port |
| `NODE_EXTRA_CA_CERTS` | -- | Path to a PEM file containing additional CA certificates for TLS verification if the pod's trust store doesn't have them |
| `MAX_HEAP_MB` | `1920` (Helm) / `1024` (Docker) | Node.js V8 max old space size in MB |

Secret values in tenant YAML files are referenced via the `os.environ/` prefix (e.g., `os.environ/CONFLUENCE_CLIENT_SECRET`). The conventional environment variable names are `CONFLUENCE_CLIENT_SECRET`, `CONFLUENCE_PAT`, and `ZITADEL_CLIENT_SECRET`, but operators can use any variable name as long as the `os.environ/` reference in the tenant YAML matches. See [Authentication -- Secret Resolution](./authentication.md#secret-resolution) for the full resolution mechanism, supported fields, and Kubernetes integration.

## Tenant Configuration File

### File Naming and Loading

Tenant configuration files must follow the naming convention `{tenant-name}-tenant-config.yaml`. The tenant name is extracted from the filename by removing the `-tenant-config.yaml` suffix and must match the pattern `^[a-z0-9]+(-[a-z0-9]+)*$` (lowercase alphanumeric with hyphens). Duplicate tenant names cause a startup failure.

The connector loads all files matching the `TENANT_CONFIG_PATH_PATTERN` glob at startup. At least one file must match the pattern, and at least one tenant must have `active` status. For details on how tenants are isolated at runtime, see [Architecture -- Multi-Tenancy Support](../technical/architecture.md#multi-tenancy-support).

### Tenant Status

Each tenant configuration file can include a top-level `status` field:

| Status | Default | Behavior                                        |
|---|---|-------------------------------------------------|
| `active` | Yes | Tenant is loaded and sync jobs are scheduled    |
| `inactive` | -- | Tenant config is validated but no sync jobs run |
| `deleted` | -- | Tenant is skipped entirely (for now)            |

### Complete Example (Cloud + External Auth)

```yaml
confluence:
  instanceType: cloud
  baseUrl: https://your-domain.atlassian.net
  cloudId: your-cloud-id
  auth:
    mode: oauth_2lo
    clientId: your-oauth-client-id
    clientSecret: os.environ/CONFLUENCE_CLIENT_SECRET
  apiRateLimitPerMinute: 100
  ingestSingleLabel: ai-ingest
  ingestAllLabel: ai-ingest-all

unique:
  serviceAuthMode: external
  zitadelOauthTokenUrl: https://auth.your-unique-instance.com/oauth/v2/token
  zitadelProjectId: your-zitadel-project-id
  zitadelClientId: confluence-connector
  zitadelClientSecret: os.environ/ZITADEL_CLIENT_SECRET
  ingestionServiceBaseUrl: https://ingestion.your-unique-instance.com
  scopeManagementServiceBaseUrl: https://scope-management.your-unique-instance.com
  apiRateLimitPerMinute: 100

processing:
  concurrency: 1
  scanIntervalCron: "*/15 * * * *"

ingestion:
  ingestionMode: flat
  scopeId: your-scope-id
  storeInternally: enabled
```

### Complete Example (Data Center + Cluster-Local Auth)

```yaml
confluence:
  instanceType: data-center
  baseUrl: https://confluence.your-company.com
  auth:
    mode: oauth_2lo
    clientId: your-confluence-app-client-id
    clientSecret: os.environ/CONFLUENCE_CLIENT_SECRET
  apiRateLimitPerMinute: 50
  ingestSingleLabel: ai-ingest
  ingestAllLabel: ai-ingest-all

unique:
  serviceAuthMode: cluster_local
  serviceExtraHeaders:
    x-company-id: your-company-id
    x-user-id: your-user-id
  ingestionServiceBaseUrl: http://node-ingestion.<namespace>:8091
  scopeManagementServiceBaseUrl: http://node-scope-management.<namespace>:8094
  apiRateLimitPerMinute: 100

processing:
  concurrency: 1
  scanIntervalCron: "0 */2 * * *"

ingestion:
  ingestionMode: flat
  scopeId: your-scope-id
  storeInternally: enabled
```

## Confluence Connection Settings

The `confluence` section configures how the connector connects to the Confluence instance:

```yaml
confluence:
  instanceType: cloud
  baseUrl: https://your-domain.atlassian.net
  cloudId: your-cloud-id
  auth:
    mode: oauth_2lo
    clientId: your-oauth-client-id
    clientSecret: os.environ/CONFLUENCE_CLIENT_SECRET
  apiRateLimitPerMinute: 100
  ingestSingleLabel: ai-ingest
  ingestAllLabel: ai-ingest-all
```

| Field | Required | Default | Description |
|---|---|---|---|
| `instanceType` | Yes | -- | `cloud` or `data-center` |
| `baseUrl` | Yes | -- | Base URL of the Confluence instance (e.g., `https://acme.atlassian.net`). Must not end with a trailing slash |
| `cloudId` | Yes (Cloud only) | -- | Atlassian Cloud ID (UUID) for the Confluence site |
| `auth` | Yes | -- | Authentication configuration (see [Authentication](./authentication.md#confluence-authentication-methods)) |
| `apiRateLimitPerMinute` | Yes | -- | Number of Confluence API requests allowed per minute |
| `ingestSingleLabel` | Yes | -- | Confluence label that marks individual pages for synchronization (e.g., `ai-ingest`) |
| `ingestAllLabel` | Yes | -- | Confluence label that marks a page and all its descendants for synchronization (e.g., `ai-ingest-all`) |

**Important:** `ingestSingleLabel` and `ingestAllLabel` are required fields with no schema default. Operators must explicitly configure them.

**Important:** `apiRateLimitPerMinute` is a required field with no schema default. Atlassian recommends Data Center admins allow at least 20 requests/second (1200 RPM). Cloud uses a points-based quota -- consult the [Atlassian REST API rate limiting documentation](https://developer.atlassian.com/cloud/confluence/rate-limiting/) for details.

### Authentication

For full details on authentication setup, credential management, secret resolution, and token flows, see [Authentication](./authentication.md).

### Space Scanning

The connector discovers pages via Confluence Query Language (CQL) label searches. Only pages in the following space types are scanned:

| Instance Type | Space Types Scanned |
|---|---|
| Cloud | `global`, `collaboration` |
| Data Center | `global` |

## Unique Platform Settings

The `unique` section configures how the connector communicates with the Unique platform. The field for selecting the auth mode is `serviceAuthMode` (not `authMode`).

> **Note:** The Helm chart `values.yaml` uses `unique.authMode`, which the Helm template maps to `serviceAuthMode` in the generated tenant config YAML. See [Authentication -- Helm Chart Field Mapping](./authentication.md#helm-chart-field-mapping).

```yaml
unique:
  serviceAuthMode: cluster_local
  ingestionServiceBaseUrl: http://node-ingestion.<namespace>:8091
  scopeManagementServiceBaseUrl: http://node-scope-management.<namespace>:8094
  apiRateLimitPerMinute: 100
  serviceExtraHeaders:
    x-company-id: "company-id"
    x-user-id: "service-user-id"
```

| Field | Required | Default | Description |
|---|---|---|---|
| `serviceAuthMode` | Yes | -- | `cluster_local` or `external` |
| `ingestionServiceBaseUrl` | Yes | -- | Base URL for the Unique ingestion service. Must not end with a trailing slash |
| `scopeManagementServiceBaseUrl` | Yes | -- | Base URL for the Unique scope management service. Must not end with a trailing slash |
| `apiRateLimitPerMinute` | No | `100` | Number of Unique API requests allowed per minute |

The additional fields required for each auth mode (`serviceExtraHeaders` for `cluster_local`, Zitadel credentials for `external`) are documented in the [Authentication Guide -- Unique Platform Authentication Methods](./authentication.md#unique-platform-authentication-methods), which also covers setup instructions and token flows.

## Ingestion Settings

The `ingestion` section configures how content is organized and stored in the Unique knowledge base:

```yaml
ingestion:
  ingestionMode: flat
  scopeId: your-scope-id
  storeInternally: enabled
  useV1KeyFormat: disabled
  attachments:
    mode: enabled
    allowedExtensions:
      - pdf
      - docx
      - xlsx
      - ppt
      - pptx
      - txt
      - csv
      - html
    maxFileSizeMb: 200
```

| Field | Required | Default | Description |
|---|---|---|---|
| `ingestionMode` | No | `flat` | Ingestion traversal mode. Currently only `flat` is supported (all pages from a space go into a single scope per space) |
| `scopeId` | Yes | -- | Root scope ID in the Unique platform. The scope must exist before the connector starts (see [Authentication -- Create the Root Scope in Unique](./authentication.md#2-create-the-root-scope-in-unique)) |
| `storeInternally` | No | `enabled` | Whether to store content internally in Unique (`enabled` or `disabled`) |
| `useV1KeyFormat` | No | `disabled` | Use v1-compatible ingestion key format (`spaceId_spaceKey/pageId`) without tenant prefix (`enabled` or `disabled`). Only relevant when migrating from Confluence Connector v1 |
| `attachments` | No | (see sub-fields) | Configuration for file attachment ingestion |

### Attachment Configuration

The `attachments` sub-section controls ingestion of file attachments from Confluence pages:

| Field | Required | Default | Description |
|---|---|---|---|
| `attachments.mode` | No | `enabled` | Whether to ingest file attachments (`enabled` or `disabled`) |
| `attachments.allowedExtensions` | No | `pdf`, `docx`, `xlsx`, `ppt`, `pptx`, `txt`, `csv`, `html` | File extensions to include when ingesting attachments. Values are case-insensitive |
| `attachments.maxFileSizeMb` | No | `200` | Maximum file size in megabytes. Attachments larger than this are skipped |

## Processing Settings

The `processing` section controls sync scheduling and concurrency:

```yaml
processing:
  concurrency: 1
  scanIntervalCron: "*/15 * * * *"
  # maxItemsToScan: 100
```

| Field | Required | Default | Description |
|---|---|---|---|
| `concurrency` | No | `1` | Number of pages/attachments to submit for ingestion into Unique concurrently |
| `scanIntervalCron` | No | `*/15 * * * *` | Cron expression for the scheduled sync interval |
| `maxItemsToScan` | No | -- (unlimited) | Maximum number of items (pages + attachments) to scan per run. Intended for testing purposes |

## Scheduler and Sync Interval

The connector runs sync cycles on a per-tenant cron schedule. Key behaviors:

- An **initial sync is triggered immediately** on startup for each active tenant.
- Subsequent syncs run according to the `scanIntervalCron` expression.
- If a sync cycle for a tenant is still running when the next is scheduled, the new cycle is **skipped** (concurrent sync prevention).
- During shutdown, all cron jobs are stopped gracefully.

**Considerations:**

- Lower intervals increase Confluence API usage and may hit rate limits.
- Higher intervals delay sync of new content.
- Adjust `concurrency` and `apiRateLimitPerMinute` for large instances with many pages.

## Logging

### Structured JSON Logs

The connector produces structured JSON logs. In production (`NODE_ENV=production`), logs are written as JSON to stdout. In development, logs use a human-readable format.

### Log Levels

Set via the `LOG_LEVEL` environment variable:

| Level | Description |
|---|---|
| `fatal` | Unrecoverable errors |
| `error` | Error conditions |
| `warn` | Warning conditions |
| `info` | General operational information (default) |
| `debug` | Detailed debugging information |
| `trace` | Very detailed trace-level information |
| `silent` | No logging output |

### Tenant Context in Logs

Every log entry emitted within a tenant sync context automatically includes the `tenantName` field.

### Diagnostics Data Policy

The `LOGS_DIAGNOSTICS_DATA_POLICY` environment variable controls how diagnostic data (emails, usernames, IDs) appears in logs:

| Value | Behavior |
|---|---|
| `conceal` (default) | Partially masks values (e.g., `John Smith` becomes `**** *mith`) |
| `disclose` | Shows values in full |

This applies to diagnostic data only. Actual secrets (passwords, tokens, keys) are always fully redacted regardless of this setting.

### Sensitive Header Redaction

The `authorization` request header is automatically redacted in HTTP request logs.

## Metrics

### OpenTelemetry Integration

The connector uses [OpenTelemetry](https://opentelemetry.io/) for metrics. To enable Prometheus metrics export, set the following environment variables:

```yaml
connector:
  env:
    OTEL_METRICS_EXPORTER: "prometheus"
    OTEL_EXPORTER_PROMETHEUS_HOST: "0.0.0.0"
    OTEL_EXPORTER_PROMETHEUS_PORT: "51350"
```

The Helm chart ships these values by default.

### Host and API Metrics

The connector exposes standard host metrics (CPU, memory, event loop) and HTTP API metrics.

Unique API metrics and custom connector metrics will be documented in a future update.

### Grafana Dashboard

A Grafana dashboard ConfigMap is available in the Helm chart. The dashboard visualizes sync durations, content throughput, attachment uploads, Confluence API performance, Unique API performance, and Node.js runtime metrics. Enable it with:

```yaml
grafana:
  dashboard:
    enabled: true
    folder: connectors
```

### Alerts

#### Default Alerts

The Helm chart provides one default alert:

| Category | Alert Name | Description |
|---|---|---|
| `uniqueApi` | `ConfluenceConnectorUniqueAPIErrors` | Fires when the Unique API error rate (4xx/5xx responses) exceeds the configured threshold |

**Default alert parameters:**

| Parameter | Default Value |
|---|---|
| `threshold` | `0.01` (1% error rate) |
| `for` | `30s` |
| `severity` | `warning` |

#### Alert Configuration

Enable alerts and customize per-alert parameters in Helm `values.yaml`:

```yaml
alerts:
  enabled: true
  defaultAlerts:
    uniqueApi:
      enabled: true
      # Disable specific alerts:
      disabled: {}
        # ConfluenceConnectorUniqueAPIErrors: true
      # Override alert parameters:
      customRules: {}
        # ConfluenceConnectorUniqueAPIErrors:
        #   for: "15s"
        #   severity: "critical"
        #   threshold: 0.05
    additionalLabels: {}
      # environment: production
      # team: backend
```

Alerts require the `monitoring.coreos.com/v1` API (Prometheus Operator) to be available in the cluster.

## Complete Re-ingestion

To perform a complete re-ingestion of all synced Confluence content:

### Prerequisites

- Access to the Unique API or admin interface
- Ability to pause the connector

### Step 1: Pause the Connector

Scale down the deployment:

```bash
kubectl scale deployment confluence-connector --replicas=0 -n <namespace>
```

### Step 2: Delete Synced Content Under the Root Scope

Use the Unique Public API or admin interface to remove the connector-managed content under the configured root scope.

Do not delete the root scope itself. The connector validates that the scope referenced by `ingestion.scopeId` exists at the start of each sync cycle. If the scope is missing, the sync cycle fails. The application remains running but every sync attempt fails until the scope is restored or the configuration is corrected.

**Warning:** This operation is irreversible. Ensure you have backups if needed.

### Step 3: Re-enable the Connector

Scale up the deployment:

```bash
kubectl scale deployment confluence-connector --replicas=1 -n <namespace>
```

The connector triggers an initial sync immediately on startup, re-ingesting all labeled content from scratch into the existing root scope.

### Further Guidance

A dedicated re-ingestion runbook with extended prerequisites, API request examples, and operational caveats will be linked here in a later documentation update.
