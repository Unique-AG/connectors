<!-- confluence-page-id: 2150170631 -->
<!-- confluence-space-key: PUBDOC -->

## Configuration Overview

The Confluence Connector uses a **YAML-based tenant configuration file** for all settings. The configuration file path is specified via the `TENANT_CONFIG_PATH_PATTERN` environment variable.

## Environment Variables

The following environment variables control application-level behavior. They are set outside the tenant configuration YAML (typically in Helm `connector.env`).

| Variable                       | Default                        | Description                                                                                                                                   |
|--------------------------------|--------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------|
| `NODE_ENV`                     | `production`                   | Environment mode (`development`, `production`, `test`)                                                                                        |
| `PORT`                         | `51349`                        | HTTP port the application binds to                                                                                                            |
| `LOG_LEVEL`                    | `info`                         | Log verbosity: `error`, `warn`, `info`, `debug`. See [Logging](#Logging)                                                                      |
| `LOGS_DIAGNOSTICS_DATA_POLICY` | `conceal`                      | Controls whether diagnostic data (emails, usernames, IDs) is logged in full (`disclose`) or partially masked (`conceal`). See [Logging](#Diagnostics-Data-Policy) |
| `TENANT_CONFIG_PATH_PATTERN`   | -- (required; Helm chart sets `/app/tenant-configs/*-tenant-config.yaml`) | Glob pattern to tenant configuration YAML files                                                                              |
| `OTEL_METRICS_EXPORTER`        | --                             | OpenTelemetry metrics exporter (e.g., `prometheus`). See [Metrics](#Metrics)                                                                  |
| `OTEL_EXPORTER_PROMETHEUS_HOST` | --                            | Prometheus exporter bind host                                                                                                                 |
| `OTEL_EXPORTER_PROMETHEUS_PORT` | --                            | Prometheus exporter bind port                                                                                                                 |
| `NODE_EXTRA_CA_CERTS`          | --                             | Path to a PEM file containing additional CA certificates for TLS verification if the pod's trust store doesn't have them                      |
| `MAX_HEAP_MB`                  | `1920` (Helm) / `1024` (Docker) | Node.js V8 max old space size in MB                                                                                                         |
| `HEALTH_SYNC_HISTORY_SIZE`     | `5`                            | Number of recent sync runs kept per tenant in the sliding window for health evaluation. See [Health Endpoint](#Health-Endpoint)               |
| `HEALTH_SYNC_TENANT_FAILURE_THRESHOLD` | `0.5`                  | Per-tenant failure ratio (0--1) across the window that marks the service unhealthy when exceeded. See [Health Endpoint](#Health-Endpoint)     |
| `HEALTH_CONNECTIVITY_TIMEOUT_MS` | `3000`                       | Timeout in milliseconds for each reachability ping used by the health endpoint. See [Health Endpoint](#Health-Endpoint)                       |

The following environment variables are typically loaded from Kubernetes Secrets:

| Variable                  | Description                                                                                  |
|---------------------------|----------------------------------------------------------------------------------------------|
| `CONFLUENCE_CLIENT_SECRET` | OAuth 2.0 client secret (used when `confluence.auth.mode` is `oauth_2lo`)                   |
| `CONFLUENCE_PAT`          | Personal Access Token (used when `confluence.auth.mode` is `pat`; Data Center below 10.1 only) |
| `ZITADEL_CLIENT_SECRET`   | Zitadel client secret (required when `unique.serviceAuthMode` is `external`)                 |
| `PROXY_PASSWORD`          | Proxy password (required when proxy `authMode` is `username_password`)                       |

Secret values in tenant YAML files are referenced via the `os.environ/` prefix (e.g., `os.environ/CONFLUENCE_CLIENT_SECRET`). The conventional environment variable names are listed above, but operators can use any variable name as long as the `os.environ/` reference in the tenant YAML matches. See [Authentication -- Secret Resolution](./authentication.md#Secret-Resolution) for the full resolution mechanism, supported fields, and Kubernetes integration.

## Tenant Configuration File

### File Naming and Loading

Tenant configuration files must follow the naming convention `{tenant-name}-tenant-config.yaml`. The tenant name is extracted from the filename by removing the `-tenant-config.yaml` suffix and must match the pattern `^[a-z0-9]+(-[a-z0-9]+)*$` (lowercase alphanumeric with hyphens). Duplicate tenant names cause a startup failure.

The connector loads all files matching the `TENANT_CONFIG_PATH_PATTERN` glob at startup. At least one file must match the pattern, and at least one tenant must have `active` or `deleted` status. For details on how tenants are isolated at runtime, see [Architecture -- Multi-Tenancy Support](../technical/architecture.md#Multi-Tenancy-Support).

### Tenant Status

Each tenant configuration file can include a top-level `status` field:

| Status     | Default | Behavior                                                                            |
|------------|---------|------------------------------------------------------------------------------------|
| `active`   | Yes     | Tenant is loaded and sync jobs are scheduled                                        |
| `inactive` | --      | Tenant config is validated but no sync jobs run                                     |
| `deleted`  | --      | Ingested content is deleted from the Unique knowledge base and sync is stopped |

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
  pageIngestionConfig:
    htmlConfig:
      imageContentExtraction:
        enabled: true
        languageModel: your-kb-visual-llm
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
  pageIngestionConfig:
    htmlConfig:
      imageContentExtraction:
        enabled: true
        languageModel: your-kb-visual-llm
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

| Field                  | Required         | Default | Description                                                                                                  |
|------------------------|------------------|---------|--------------------------------------------------------------------------------------------------------------|
| `instanceType`         | Yes              | --      | `cloud` or `data-center`                                                                                     |
| `baseUrl`              | Yes              | --      | Base URL of the Confluence instance (e.g., `https://acme.atlassian.net`). Must not end with a trailing slash |
| `cloudId`              | Yes (Cloud only) | --      | Atlassian Cloud ID (UUID) for the Confluence site                                                            |
| `auth`                 | Yes              | --      | Authentication configuration (see [Authentication](./authentication.md#Confluence-Authentication-Methods))   |
| `apiRateLimitPerMinute` | Yes             | --      | Number of Confluence API requests allowed per minute                                                         |
| `ingestSingleLabel`    | Yes              | --      | Confluence label that marks individual pages for synchronization (e.g., `ai-ingest`)                         |
| `ingestAllLabel`       | Yes              | --      | Confluence label that marks a page and all its descendants for synchronization (e.g., `ai-ingest-all`)       |

**Important:** `ingestSingleLabel` and `ingestAllLabel` are required fields with no schema default. Operators must explicitly configure them.

**Important:** `apiRateLimitPerMinute` is a required field with no schema default. Atlassian recommends Data Center admins allow at least 20 requests/second (1200 RPM). Cloud uses a points-based quota -- consult the [Atlassian REST API rate limiting documentation](https://developer.atlassian.com/cloud/confluence/rate-limiting/) for details.

### Authentication

For full details on authentication setup, credential management, secret resolution, and token flows, see [Authentication](./authentication.md).

### Space Scanning

The connector discovers pages via Confluence Query Language (CQL) label searches. Only pages in the following space types are scanned:

| Instance Type | Space Types Scanned      |
|---------------|--------------------------|
| Cloud         | `global`, `collaboration` |
| Data Center   | `global`                 |

## Unique Platform Settings

The `unique` section configures how the connector communicates with the Unique platform. The field for selecting the auth mode is `serviceAuthMode` (not `authMode`).

> **Note:** The Helm chart `values.yaml` uses `unique.authMode`, which the Helm template maps to `serviceAuthMode` in the generated tenant config YAML. See [Authentication -- Helm Chart Field Mapping](./authentication.md#Helm-Chart-Field-Mapping).

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

| Field                          | Required | Default | Description                                                                            |
|--------------------------------|----------|---------|----------------------------------------------------------------------------------------|
| `serviceAuthMode`              | Yes      | --      | `cluster_local` or `external`                                                          |
| `ingestionServiceBaseUrl`      | Yes      | --      | Base URL for the Unique ingestion service. Must not end with a trailing slash           |
| `scopeManagementServiceBaseUrl` | Yes     | --      | Base URL for the Unique scope management service. Must not end with a trailing slash    |
| `apiRateLimitPerMinute`        | No       | `100`   | Number of Unique API requests allowed per minute                                       |

The additional fields required for each auth mode (`serviceExtraHeaders` for `cluster_local`, Zitadel credentials for `external`) are documented in the [Authentication Guide -- Unique Platform Authentication Methods](./authentication.md#Unique-Platform-Authentication-Methods), which also covers setup instructions and token flows.

## Proxy Configuration

The connector supports HTTP/HTTPS forward proxies for environments where outbound internet access is only available through a proxy. Proxy settings are configured via environment variables (managed by the Helm chart's `proxyConfig` section).

| Mode                  | Description                          |
|-----------------------|--------------------------------------|
| `none`                | Proxy disabled (default)             |
| `no_auth`             | Proxy enabled without authentication |
| `username_password`   | Basic authentication proxy           |
| `ssl_tls`             | TLS client certificate proxy         |

**Common options** (required for `no_auth`, `username_password`, and `ssl_tls` modes):

| Variable                  | Description                                                          |
|---------------------------|----------------------------------------------------------------------|
| `PROXY_HOST`              | Proxy server hostname                                                |
| `PROXY_PORT`              | Proxy server port                                                    |
| `PROXY_PROTOCOL`          | `http` or `https`                                                    |
| `PROXY_SSL_CA_BUNDLE_PATH` | (Optional) Path to CA bundle for verifying proxy TLS certificate    |
| `PROXY_HEADERS`           | (Optional) JSON string of custom headers for CONNECT request         |

**`username_password` mode** adds:

| Variable         | Description                              |
|------------------|------------------------------------------|
| `PROXY_USERNAME` | Proxy username                           |
| `PROXY_PASSWORD` | Proxy password (loaded from secret)      |

**`ssl_tls` mode** adds:

| Variable              | Description                    |
|-----------------------|--------------------------------|
| `PROXY_SSL_CERT_PATH` | Path to TLS client certificate |
| `PROXY_SSL_KEY_PATH`  | Path to TLS client key         |

### Traffic Routing

When the proxy is enabled, traffic is routed as follows:

| Target                                          | Routing                                                                                                     |
|-------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Confluence API (Cloud or Data Center)            | Always through the proxy                                                                                    |
| Atlassian or Data Center OAuth token endpoint    | Always through the proxy                                                                                    |
| Unique Ingestion and Scope Management services   | Through the proxy only when `unique.serviceAuthMode` is `external`. Bypassed in `cluster_local` mode       |
| Attachment and content uploads to Unique         | Same routing as Unique API calls above                                                                      |

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
    allowedMimeTypes:
      - application/pdf
      - application/vnd.openxmlformats-officedocument.wordprocessingml.document
      - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
      - application/vnd.openxmlformats-officedocument.presentationml.presentation
      - text/plain
      - text/csv
      - text/html
      - image/png
      - image/jpeg
    maxFileSizeMb: 200
    imageOcr: enabled
  pageIngestionConfig:
    htmlConfig:
      imageContentExtraction:
        enabled: true
        languageModel: your-kb-visual-llm
```

| Field            | Required | Default          | Description                                                                                                                                                         |
|------------------|----------|------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `ingestionMode`  | No       | `flat`           | Ingestion traversal mode. Currently only `flat` is supported (all pages from a space go into a single scope per space)                                              |
| `scopeId`        | Yes      | --               | Root scope ID in the Unique platform. The scope must exist before the connector starts (see [Authentication -- Create the Root Scope in Unique](./authentication.md#2.-Create-the-Root-Scope-in-Unique)) |
| `storeInternally` | No      | `enabled`        | Whether to store content internally in Unique (`enabled` or `disabled`)                                                                                             |
| `useV1KeyFormat` | No       | `disabled`       | Use v1-compatible ingestion key format (`spaceId_spaceKey/pageId`) without tenant prefix (`enabled` or `disabled`). Only relevant when migrating from Confluence Connector v1 |
| `attachments`    | No       | (see sub-fields) | Configuration for file attachment ingestion                                                                                                                          |
| `pageIngestionConfig` | No | -- | Ingestion configuration applied to each ingested page. Setting `htmlConfig.imageContentExtraction.enabled` to `true` and `htmlConfig.imageContentExtraction.languageModel` to the visual LLM configured in Knowledge Base turns on inlining of page images as base64 `data:` URIs (see [Image Attachments](#Image-Attachments)). Without both, images fall back to standalone attachment ingestion |

### Attachment Configuration

The `attachments` sub-section controls ingestion of file attachments from Confluence pages:

| Field                          | Required | Default                          | Description                                                                        |
|--------------------------------|----------|----------------------------------|------------------------------------------------------------------------------------|
| `attachments.mode`             | No       | `enabled`                        | Whether to ingest file attachments (`enabled` or `disabled`)                       |
| `attachments.allowedMimeTypes` | No       | See [Default Allowed MIME Types](#Default-Allowed-MIME-Types) | MIME types to include when ingesting attachments. Matched against the `mediaType` reported by the Confluence API, case-insensitive |
| `attachments.maxFileSizeMb`    | No       | `200`                            | Maximum file size in megabytes. Attachments larger than this are skipped           |
| `attachments.imageOcr`         | No       | `enabled`                        | Whether the connector should request OCR-based ingestion for image attachments by attaching `ingestionConfig.jpgReadMode = DOC_INTELLIGENCE_DEFAULT` to each create-content request. When `disabled`, the destination scope's own `jpgReadMode` is used instead |

#### Default Allowed MIME Types

```yaml
- application/pdf
- application/vnd.openxmlformats-officedocument.wordprocessingml.document  # DOCX
- application/vnd.openxmlformats-officedocument.spreadsheetml.sheet        # XLSX
- application/vnd.openxmlformats-officedocument.presentationml.presentation # PPTX
- text/plain
- text/csv
- text/html
- image/png
- image/jpeg
```

These are matched against the `mediaType` reported by the Confluence API. Operators can override the list via `ingestion.attachments.allowedMimeTypes`. Note that the Unique ingestion service ultimately decides which types it can chunk; configuring a MIME type here that the ingestion service does not accept will result in upload errors at runtime.

#### Image Attachments

Images embedded in Confluence pages (drag/drop, paste, or "Insert image") are stored as regular page attachments by Confluence. When inlining is enabled, the connector inlines each referenced image directly into the page HTML as a base64 `data:` URI during page ingestion, producing a single self-contained page artifact rather than a separate image artifact. This applies to images attached to the page being ingested as well as images attached to other pages in the same Confluence instance (references to an attachment on another page). PNG and JPEG are the supported formats; both are in the default `allowedMimeTypes`.

Inlining is turned on by the presence of the image-extraction configuration the platform needs to extract searchable text from those inline images: set both `pageIngestionConfig.htmlConfig.imageContentExtraction.enabled` to `true` and `pageIngestionConfig.htmlConfig.imageContentExtraction.languageModel` to the visual LLM configured in Knowledge Base. The connector forwards this configuration verbatim with every page, and it is also what flips inlining on, so the connector never inlines images the platform cannot extract. When either field is missing, inlining is off and referenced images fall back to standalone attachment ingestion. This replaces the previous manual step of setting the extraction config on the destination scope.

> **Platform compatibility:** Inline images require Unique platform `2026.24.0` or later. The platform extracts searchable text from inline base64 images starting with that version; on earlier versions the page is still ingested but its embedded images are dropped during HTML-to-Markdown conversion and contribute no searchable content. Extraction is also gated behind two company-scoped feature flags that must be enabled (`FEATURE_FLAG_ENABLE_HTML_INLINE_IMAGE_EXTRACTION_UN_20936` and `FEATURE_FLAG_ENABLE_MULTI_FILE_IMAGE_CONTENT_EXTRACTION_UN_20936`). See [Unique Platform Compatibility](./deployment.md#Unique-Platform-Compatibility).
>
> On platforms older than `2026.24.0`, omit the `pageIngestionConfig.htmlConfig.imageContentExtraction` block (or leave `enabled` unset) so referenced images are ingested as standalone attachments (and OCR'd via `attachments.imageOcr`) instead of being inlined and lost. Add it back after upgrading.

When inlining is enabled, image attachments are not ingested as standalone artifacts. Orphan images (attached to the page but not referenced by any in-body macro) are appended to the end of the page body so their content is still inlined. A macro-referenced image that cannot be inlined (download failure, exceeds `attachments.maxFileSizeMb`, MIME type not in `allowedMimeTypes`, or a cross-page reference whose target page cannot be resolved) keeps its original `<ac:image>` macro and is not ingested elsewhere; on a transient download failure it is inlined on a later sync once the page re-ingests.

`attachments.imageOcr` only applies when inlining is off and images go through the standalone attachment path. With `attachments.imageOcr = enabled` (the default), each standalone-ingested image registration is sent with `ingestionConfig.jpgReadMode = DOC_INTELLIGENCE_DEFAULT`, which overrides the scope-level default (`NO_INGESTION`). Set `attachments.imageOcr = disabled` to leave the decision to the destination scope's own `ingestionConfig`. Images inlined into a page are processed via the page artifact and are unaffected by this flag.

Images inserted as external URLs (`<ac:image><ri:url ri:value="https://..."/></ac:image>`) are left untouched in the page HTML and are never fetched by the connector.

Other image formats (GIF, WebP, SVG, HEIC, BMP, TIFF) are not currently supported by the Unique ingestion service. Adding them to `allowedMimeTypes` will cause uploads to be rejected with HTTP 400.

## Processing Settings

The `processing` section controls sync scheduling and concurrency:

```yaml
processing:
  concurrency: 1
  scanIntervalCron: "*/15 * * * *"
  # maxItemsToScan: 100
```

| Field              | Required | Default         | Description                                                                            |
|--------------------|----------|-----------------|----------------------------------------------------------------------------------------|
| `concurrency`      | No       | `1`             | Number of pages/attachments to submit for ingestion into Unique concurrently           |
| `scanIntervalCron` | No       | `*/15 * * * *`  | Cron expression for the scheduled sync interval                                        |
| `maxItemsToScan`   | No       | -- (unlimited)  | Maximum number of items (pages + attachments) to scan per run. Intended for testing purposes |

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

| Level   | Description                               |
|---------|-------------------------------------------|
| `error` | Error conditions                          |
| `warn`  | Warning conditions                        |
| `info`  | General operational information (default) |
| `debug` | Detailed debugging information            |

### Tenant Context in Logs

Every log entry emitted within a tenant sync context automatically includes the `tenantName` field.

### Diagnostics Data Policy

The `LOGS_DIAGNOSTICS_DATA_POLICY` environment variable controls how diagnostic data (emails, usernames, IDs) appears in logs:

| Value                | Behavior                                                            |
|----------------------|---------------------------------------------------------------------|
| `conceal` (default)  | Partially masks values (e.g., `John Smith` becomes `**** *mith`)   |
| `disclose`           | Shows values in full                                                |

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

### System Telemetry

The connector exposes standard host metrics (CPU, memory, event loop) and HTTP API metrics collected by the OpenTelemetry host and API instrumentations.

### Application Telemetry

Custom connector metrics use the `cfc_` prefix (Confluence Connector). Unique platform interaction metrics use the `confluence_connector_unique_api_` prefix.

#### Sync Cycle Metrics

| Metric                                    | Type      | Labels            | Description                                              |
|-------------------------------------------|-----------|-------------------|----------------------------------------------------------|
| `cfc_sync_duration_seconds`               | Histogram | `tenant`, `result` | Duration of a full synchronization cycle per tenant     |
| `cfc_scan_duration_seconds`               | Histogram | `tenant`          | Duration of the page discovery (scan) phase              |
| `cfc_attachment_upload_duration_seconds`   | Histogram | `tenant`          | Duration of a single attachment upload to Unique         |

Attachment upload histogram buckets: 100ms, 200ms, 500ms, 1s, 2s, 3s, 5s, 10s, 20s, 30s, 60s.

#### Content Throughput Metrics

| Metric                                | Type    | Labels                        | Description                                                                      |
|---------------------------------------|---------|-------------------------------|----------------------------------------------------------------------------------|
| `cfc_pages_processed_total`           | Counter | `tenant`, `result`            | Pages ingested per sync cycle                                                    |
| `cfc_attachments_processed_total`     | Counter | `tenant`, `result`            | Attachments ingested per sync cycle                                              |
| `cfc_content_deleted_total`           | Counter | `tenant`, `result`            | Content items deleted from Unique                                                |
| `cfc_file_diff_events_total`         | Counter | `tenant`, `diff_result_type`  | File change detection events (`new`, `updated`, `deleted`, `moved`)              |
| `cfc_orphaned_scopes_cleaned_total`   | Counter | `tenant`, `result`            | Space scopes removed after their Confluence space was removed or unlabeled       |
| `cfc_orphaned_files_cleaned_total`    | Counter | `tenant`                      | Files removed during orphaned space cleanup                                      |

#### Tenant Cleanup Metrics

| Metric                                    | Type      | Labels            | Description                                              |
|-------------------------------------------|-----------|-------------------|----------------------------------------------------------|
| `cfc_cleanup_duration_seconds`            | Histogram | `tenant`, `result` | Duration of a deleted tenant content cleanup             |
| `cfc_cleanup_content_deleted_total`       | Counter   | `tenant`, `result` | Content items deleted during tenant cleanup              |
| `cfc_cleanup_scopes_deleted_total`        | Counter   | `tenant`, `result` | Scopes deleted during tenant cleanup                     |

#### Confluence API Metrics

| Metric                                            | Type      | Labels                            | Description                                                                            |
|---------------------------------------------------|-----------|-----------------------------------|----------------------------------------------------------------------------------------|
| `cfc_confluence_api_request_duration_seconds`     | Histogram | `tenant`, `endpoint`, `result`    | Request latency for Confluence API calls, keyed by a normalized endpoint path          |
| `cfc_confluence_api_throttle_events_total`        | Counter   | `tenant`                          | Confluence API rate-limit (429) events                                                 |
| `cfc_confluence_api_errors_total`                 | Counter   | `tenant`, `http_status_class`     | Confluence API error responses grouped by HTTP status class                            |

Confluence API request histogram buckets: 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s, 30s.

#### Unique API Metrics

| Metric                                                      | Type      | Labels                                                          | Description                                                          |
|-------------------------------------------------------------|-----------|-----------------------------------------------------------------|----------------------------------------------------------------------|
| `confluence_connector_unique_api_requests_total`            | Counter   | `operation`, `target`, `tenant`, `result`                       | Total Unique API requests                                            |
| `confluence_connector_unique_api_errors_total`              | Counter   | `operation`, `target`, `tenant`, `status_code_class`            | Total Unique API error responses                                     |
| `confluence_connector_unique_api_request_duration_ms`       | Histogram | `operation`, `target`, `tenant`, `result`, `status_code_class`  | Request latency for Unique API calls in milliseconds                 |
| `confluence_connector_unique_api_slow_requests_total`       | Counter   | `operation`, `target`, `tenant`, `duration_bucket`              | Slow Unique API requests                                             |
| `confluence_connector_unique_api_auth_token_refresh_total`  | Counter   | --                                                              | Zitadel auth token refreshes (only emitted in `external` mode)       |

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

| Category    | Alert Name                              | Description                                                                          |
|-------------|-----------------------------------------|--------------------------------------------------------------------------------------|
| `uniqueApi` | `ConfluenceConnectorUniqueAPIErrors`    | Fires when the Unique API error rate (4xx/5xx responses) exceeds the configured threshold |

**Default alert parameters:**

| Parameter   | Default Value          |
|-------------|------------------------|
| `threshold` | `0.01` (1% error rate) |
| `for`       | `30s`                  |
| `severity`  | `warning`              |

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

## Health Endpoint

The connector exposes a `GET /health` endpoint that reports operational health. It is separate from the existing `GET /probe` endpoint used for K8s liveness/readiness probes. `GET /health` is intended for external monitoring and SRE tooling.

The endpoint returns HTTP `200` when all checks pass and HTTP `503` when any check fails. The response follows the `@nestjs/terminus` format with `status`, `info`, `error`, and `details` fields.

### Health Checks

The endpoint runs three checks on every request:

**Sync** -- Evaluates each active tenant's sync history from a sliding window of the last N runs (configurable via `HEALTH_SYNC_HISTORY_SIZE`). Each tenant's failure ratio is computed independently as `failures / appearances`. If any tenant exceeds `HEALTH_SYNC_TENANT_FAILURE_THRESHOLD`, the check is `down`. When no sync has completed yet (e.g. shortly after startup), this check reports `up` with `message: "No sync records yet"`. A single transient failure is absorbed by the window and does not trigger an alert. Skipped runs caused by an in-progress sync overlap are not recorded so they cannot dilute the window.

Sync health is evaluated at tenant level. In the Confluence connector, each tenant owns its own cron job, configuration, credentials, and operational lifecycle, so a tenant is the smallest unit that can independently fail or recover. Per-item ingestion failures are exposed through logs and metrics; `/health.sync` answers whether each active tenant's scheduled sync is consistently succeeding.

**Connectivity** -- Performs unauthenticated HTTP requests to the Atlassian API host (`https://api.atlassian.com/`, only when at least one Cloud tenant is configured) and to each unique active tenant `confluence.baseUrl`. Any HTTP response (including 401/403) proves the endpoint is reachable -- only transport-level failures (DNS, TLS, timeout, connection refused) are treated as unhealthy. Deleted tenants are excluded because they no longer talk to Confluence.

**Unique API** -- Sends a minimal `{ __typename }` GraphQL query to each tenant's ingestion and scope-management endpoints, using the same auth and proxy routing the connector uses for production traffic. Non-2xx responses (401/403/500) are treated as unhealthy because they indicate the API is not functioning correctly. If token acquisition itself fails (Zitadel outage), the tenant's entry reports `error: "AUTH_FAILURE"`. These requests bypass the per-tenant rate limiter to avoid queuing behind sync traffic.

### Response Examples

**Healthy (200):**

```json
{
  "status": "ok",
  "info": {
    "sync": {
      "status": "up",
      "lastSyncAt": "2026-04-27T10:15:00.000Z",
      "tenants": {
        "tenant-a": { "failures": 0, "total": 5 },
        "tenant-b": { "failures": 1, "total": 5 }
      }
    },
    "connectivity": {
      "status": "up",
      "atlassian": "reachable",
      "confluence": [
        { "tenant": "tenant-a", "status": "reachable" },
        { "tenant": "tenant-b", "status": "reachable" }
      ]
    },
    "uniqueApi": {
      "status": "up",
      "ingestion": [
        { "tenant": "tenant-a", "status": "reachable" },
        { "tenant": "tenant-b", "status": "reachable" }
      ],
      "scopeManagement": [
        { "tenant": "tenant-a", "status": "reachable" },
        { "tenant": "tenant-b", "status": "reachable" }
      ]
    }
  },
  "error": {},
  "details": { "...same as info when healthy..." }
}
```

**Unhealthy (503) -- a tenant exceeds the sync failure threshold:**

```json
{
  "status": "error",
  "info": {
    "connectivity": { "status": "up", "...": "..." },
    "uniqueApi": { "status": "up", "...": "..." }
  },
  "error": {
    "sync": {
      "status": "down",
      "lastSyncAt": "2026-04-27T10:15:00.000Z",
      "threshold": 0.5,
      "failingTenants": ["tenant-b"],
      "tenants": {
        "tenant-a": { "failures": 0, "total": 5 },
        "tenant-b": { "failures": 4, "total": 5 }
      }
    }
  },
  "details": { "...all checks combined..." }
}
```

### Configuration

| Variable                                | Default | Description                                                              |
|-----------------------------------------|---------|--------------------------------------------------------------------------|
| `HEALTH_SYNC_HISTORY_SIZE`              | `5`     | Number of recent sync runs kept per tenant in the sliding window         |
| `HEALTH_SYNC_TENANT_FAILURE_THRESHOLD`  | `0.5`   | Per-tenant failure ratio (0--1) that triggers unhealthy when exceeded    |
| `HEALTH_CONNECTIVITY_TIMEOUT_MS`        | `3000`  | Timeout in milliseconds for each reachability ping (connectivity checks) |

## Complete Re-ingestion

To perform a complete re-ingestion of all synced Confluence content:

### Prerequisites

- Access to the Unique API or admin interface
- Ability to update the tenant configuration

### Step 1: Delete Ingested Content

Set the tenant status to `deleted` in its YAML configuration file and restart the connector. The cleanup runs immediately on startup and deletes all ingested files and child scopes while preserving the root scope. In a multi-tenant deployment, all other tenants configured in the same connector instance continue syncing normally and are not affected by this operation.

**Warning:** This operation is irreversible. Ensure you have backups if needed.

### Step 2: Re-enable the Tenant

Set the tenant status back to `active` and restart the connector. The connector triggers an initial sync immediately on startup, re-ingesting all labeled content from scratch into the preserved root scope (no new scope needs to be created).

### Further Guidance

A dedicated re-ingestion runbook with extended prerequisites, API request examples, and operational caveats will be linked here in a later documentation update.
