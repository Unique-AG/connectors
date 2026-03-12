<!-- confluence-page-id: 1953824805 -->
<!-- confluence-space-key: PUBDOC -->

## Configuration Overview

The SharePoint Connector uses a **YAML-based tenant configuration file** for all settings. The configuration file path is specified via the `TENANT_CONFIG_PATH_PATTERN` environment variable.

## Environment Variables

The following environment variables control application-level behavior. They are set outside the tenant configuration YAML (typically in Helm `connector.env`).

| Variable                              | Default                                           | Description                                                                                                          |
| ------------------------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `NODE_ENV`                            | `production`                                      | Environment mode (`development`, `production`, `test`)                                                               |
| `PORT`                                | `9542`                                            | HTTP port the application binds to                                                                                   |
| `LOG_LEVEL`                           | `info`                                            | Log verbosity: `fatal`, `error`, `warn`, `info`, `debug`, `trace`, `silent`                                          |
| `LOGS_DIAGNOSTICS_DATA_POLICY`        | `conceal`                                         | Controls whether sensitive data (site names, file names) is logged in full (`disclose`) or redacted (`conceal`)      |
| `LOGS_DIAGNOSTICS_CONFIG_EMIT_POLICY` | `{"emit":"on","events":["on_startup","on_sync"]}` | JSON object controlling when configuration is logged. Set `emit` to `off` to disable                                 |
| `TENANT_CONFIG_PATH_PATTERN`          | — (required)                                      | Glob pattern to tenant configuration YAML files (e.g., `/app/tenant-configs/*-tenant-config.yaml`)                   |
| `OTEL_METRICS_EXPORTER`               | —                                                 | OpenTelemetry metrics exporter (e.g., `prometheus`)                                                                  |
| `OTEL_EXPORTER_PROMETHEUS_HOST`       | —                                                 | Prometheus exporter bind host                                                                                        |
| `OTEL_EXPORTER_PROMETHEUS_PORT`       | —                                                 | Prometheus exporter bind port                                                                                        |
| `NODE_EXTRA_CA_CERTS`                 | —                                                 | Path to a PEM file containing additional CA certificates for TLS verification if pod's trust store doesn't have them |

The following environment variables are loaded from Kubernetes secrets:

| Variable                               | Description                                                                                     |
| -------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD` | Password for an encrypted certificate private key (optional, only if key is password-protected) |
| `ZITADEL_CLIENT_SECRET`                | Zitadel client secret (required when `unique.serviceAuthMode` is `external`)                    |
| `PROXY_PASSWORD`                       | Proxy password (required when proxy `authMode` is `username_password`)                          |

## Configuration Sources

Sites can be configured in two ways:

| Source            | Description                                | Use Case                            |
| ----------------- | ------------------------------------------ | ----------------------------------- |
| `config_file`     | Static YAML configuration                  | Simple deployments, fixed site list |
| `sharepoint_list` | Dynamic configuration from SharePoint list | Self-service, frequent changes      |

## Tenant Configuration File

### Static Sites Configuration (config_file)

```yaml
sharepoint:
  # ... auth and base configuration ...

  sitesSource: config_file
  sites:
    - siteId: 12345678-1234-1234-1234-123456789abc
      syncColumnName: FinanceGPTKnowledge
      ingestionMode: recursive
      scopeId: scope_bu4gokr0atzj0kfiuaaaaaaa
      maxFilesToIngest: 1000
      storeInternally: enabled
      syncStatus: active
      syncMode: content_and_permissions
    - siteId: 87654321-4321-4321-4321-cba987654321
      syncColumnName: HRKnowledge
      ingestionMode: flat
      scopeId: scope_bu4gokr0atzj0kfiubbbbbb
      storeInternally: enabled
      syncStatus: active
      syncMode: content_only
      permissionsInheritanceMode: inherit_scopes_and_files
```

### Dynamic Sites Configuration (sharepoint_list)

Configure sites dynamically via a SharePoint list:

```yaml
sharepoint:
  # ... auth and base configuration ...

  sitesSource: sharepoint_list
  sharepointList:
    siteId: your-config-site-id-here
    listId: 00000000-0000-0000-0000-000000000000
```

You can use [the CSV import template](./Template [env-name] Sites to Sync to Unique.csv) when populating the SharePoint list for `sharepoint_list`-based configuration.

## SharePoint Base Configuration

The `sharepoint` section of the tenant YAML contains authentication and base settings that apply to all sites:

```yaml
sharepoint:
  tenantId: 12345678-1234-1234-1234-123456789012
  baseUrl: https://acme.sharepoint.com
  graphApiRateLimitPerMinuteThousands: 780
  auth:
    mode: certificate
    clientId: 00000000-0000-0000-0000-000000000000
    privateKeyPath: /app/key.pem
    thumbprintSha1: AB12CD34EF56...
```

| Option                                | Required | Default | Description                                                                                      |
| ------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------ |
| `tenantId`                            | Yes      | —       | Azure AD tenant ID                                                                               |
| `baseUrl`                             | Yes      | —       | Company SharePoint URL (e.g., `https://acme.sharepoint.com`). Must not end with a trailing slash |
| `graphApiRateLimitPerMinuteThousands` | No       | `780`   | Microsoft Graph API rate limit in thousands of requests per minute                               |
| `auth`                                | Yes      | —       | Authentication configuration (see below)                                                         |

### Authentication

The connector uses certificate-based authentication (`auth.mode: certificate`):

| Option                    | Required                    | Description                                                                          |
| ------------------------- | --------------------------- | ------------------------------------------------------------------------------------ |
| `auth.mode`               | Yes                         | `certificate`                                                                        |
| `auth.clientId`           | Yes                         | Azure AD application client ID                                                       |
| `auth.privateKeyPath`     | Yes                         | Path to the private key file in PEM format                                           |
| `auth.thumbprintSha1`     | One of SHA1/SHA256 required | SHA-1 thumbprint of the certificate                                                  |
| `auth.thumbprintSha256`   | One of SHA1/SHA256 required | SHA-256 thumbprint of the certificate                                                |
| `auth.privateKeyPassword` | No                          | Injected from `SHAREPOINT_AUTH_PRIVATE_KEY_PASSWORD` env var if the key is encrypted |

## Unique Platform Configuration

The `unique` section configures how the connector communicates with the Unique platform:

```yaml
unique:
  serviceAuthMode: cluster_local
  ingestionServiceBaseUrl: http://node-ingestion.finance-gpt:8091
  scopeManagementServiceBaseUrl: http://node-scope-management.finance-gpt:8094
  apiRateLimitPerMinute: 100
  serviceExtraHeaders:
    x-company-id: "company-id"
    x-user-id: "service-user-id"
```

| Option                          | Required | Default | Description                                                                                                    |
| ------------------------------- | -------- | ------- | -------------------------------------------------------------------------------------------------------------- |
| `serviceAuthMode`               | Yes      | —       | `cluster_local` or `external`                                                                                  |
| `ingestionServiceBaseUrl`       | Yes      | —       | Base URL for the Unique ingestion service                                                                      |
| `scopeManagementServiceBaseUrl` | Yes      | —       | Base URL for the Unique scope management service                                                               |
| `apiRateLimitPerMinute`         | No       | `100`   | Rate limit for Unique API requests per minute                                                                  |
| `ingestionConfig`               | No       | —       | Optional object passed when submitting files for ingestion (e.g., `{"uniqueIngestionMode": "SKIP_INGESTION"}`) |

**`cluster_local` mode** (in-cluster communication):

| Option                | Required | Description                                         |
| --------------------- | -------- | --------------------------------------------------- |
| `serviceExtraHeaders` | Yes      | Must contain `x-company-id` and `x-user-id` headers |

**`external` mode** (authenticates via Zitadel):

| Option                 | Required | Description                                   |
| ---------------------- | -------- | --------------------------------------------- |
| `zitadelOauthTokenUrl` | Yes      | Zitadel OAuth token URL                       |
| `zitadelProjectId`     | Yes      | Zitadel project ID                            |
| `zitadelClientId`      | Yes      | Zitadel client ID                             |
| `zitadelClientSecret`  | Yes      | Injected from `ZITADEL_CLIENT_SECRET` env var |

## Proxy Configuration

The connector supports HTTP/HTTPS proxy for environments where internet access is only available through a proxy. Proxy settings are configured via environment variables (managed by the Helm chart's `proxyConfig` section).

| Mode                | Description                  |
| ------------------- | ---------------------------- |
| `none`              | Proxy disabled (default)     |
| `username_password` | Basic authentication proxy   |
| `ssl_tls`           | TLS client certificate proxy |

**Common options** (required for `username_password` and `ssl_tls` modes):

| Variable                   | Description                                                      |
| -------------------------- | ---------------------------------------------------------------- |
| `PROXY_HOST`               | Proxy server hostname                                            |
| `PROXY_PORT`               | Proxy server port                                                |
| `PROXY_PROTOCOL`           | `http` or `https`                                                |
| `PROXY_SSL_CA_BUNDLE_PATH` | (Optional) Path to CA bundle for verifying proxy TLS certificate |
| `PROXY_HEADERS`            | (Optional) JSON string of custom headers for CONNECT request     |

**`username_password` mode** adds:

| Variable         | Description                         |
| ---------------- | ----------------------------------- |
| `PROXY_USERNAME` | Proxy username                      |
| `PROXY_PASSWORD` | Proxy password (loaded from secret) |

**`ssl_tls` mode** adds:

| Variable              | Description                    |
| --------------------- | ------------------------------ |
| `PROXY_SSL_CERT_PATH` | Path to TLS client certificate |
| `PROXY_SSL_KEY_PATH`  | Path to TLS client key         |

## SharePoint List Configuration

When using `sharepoint_list` as the sites source, create a SharePoint list with the following columns:

| Column Display Name          | Type             | Description                                                                                  |
| ---------------------------- | ---------------- | -------------------------------------------------------------------------------------------- |
| `siteId`                     | Single line text | SharePoint site ID (UUID or compound format: `hostname,siteCollectionId,webId` for subsites) |
| `syncColumnName`             | Single line text | Column that marks files for sync                                                             |
| `ingestionMode`              | Choice           | `flat` or `recursive`                                                                        |
| `uniqueScopeId`              | Single line text | Unique scope ID                                                                              |
| `maxFilesToIngest`           | Number           | Maximum new + updated files per sync cycle; sync fails for the site if exceeded              |
| `storeInternally`            | Choice           | `enabled` or `disabled`                                                                      |
| `syncStatus`                 | Choice           | `active`, `inactive`, or `deleted`                                                           |
| `syncMode`                   | Choice           | `content_only` or `content_and_permissions`                                                  |
| `permissionsInheritanceMode` | Choice           | Optional inheritance mode                                                                    |
| `subsitesScan`               | Choice           | `enabled` or `disabled` (default: `disabled`)                                                |

### Benefits of SharePoint List Configuration

- **Self-service**: Site owners can request sync without IT involvement
- **No redeployment**: Add/modify sites without restarting the connector
- **Audit trail**: SharePoint tracks changes to the configuration list
- **Approval workflows**: Use SharePoint approval flows for governance

## Per-Site Configuration Options

**Important:** The connector is a singleton — each SharePoint site must be configured in at most one connector process per Unique instance. Configuring the same site in multiple processes leads to conflicting state and unexpected behavior of the connector.

| Option                       | Values                                    | Default                      | Description                                                                         |
| ---------------------------- | ----------------------------------------- | ---------------------------- | ----------------------------------------------------------------------------------- |
| `siteId`                     | UUID or compound ID                       | — (required)                 | SharePoint site ID. Subsites use compound format: `hostname,siteCollectionId,webId` |
| `syncColumnName`             | String                                    | `FinanceGPTKnowledge`        | Name of the sync flag column                                                        |
| `ingestionMode`              | `flat`, `recursive`                       | — (required)                 | Flat ingests all to one scope; recursive maintains hierarchy                        |
| `scopeId`                    | String                                    | — (required)                 | Root scope ID in Unique                                                             |
| `maxFilesToIngest`           | Number                                    | — (unlimited)                | Maximum new + updated files per sync cycle; sync fails for the site if exceeded     |
| `storeInternally`            | `enabled`, `disabled`                     | `enabled`                    | Whether to store content in Unique                                                  |
| `syncStatus`                 | `active`, `inactive`, `deleted`           | `active`                     | Control sync behavior                                                               |
| `syncMode`                   | `content_only`, `content_and_permissions` | — (required)                 | What to sync                                                                        |
| `permissionsInheritanceMode` | See below                                 | `inherit_scopes_and_files`   | Inheritance settings for content_only mode                                          |
| `subsitesScan`               | `enabled`, `disabled`                     | `disabled`                   | Recursively discover and sync content from subsites                                 |

### Permissions Inheritance Modes

Only used when `syncMode` is `content_only`. It controls whether newly created scopes / files inherit permissions from their parent. If scopes / files are configured to not inherit permissions, any newly created scopes / files will not be visible to platform users, only to service user. To grant access to these new scopes / files, admin has to use API on behalf of the service user.

| Mode                       | Scopes Inherit | Files Inherit |
| -------------------------- | -------------- | ------------- |
| `inherit_scopes_and_files` | Yes            | Yes           |
| `inherit_scopes`           | Yes            | No            |
| `inherit_files`            | No             | Yes           |
| `none`                     | No             | No            |

## SharePoint Site Configuration

### Finding SharePoint Site IDs

Site IDs are required to configure which SharePoint sites the connector scans.

**Via Browser:**

Navigate to: `https://{tenant}.sharepoint.com/sites/your-site/_api/site/id`

The response will be XML containing the site ID:

```xml
<d:Id>12345678-1234-1234-1234-123456789012</d:Id>
```

**Via Microsoft Graph Explorer:**

```
GET https://graph.microsoft.com/v1.0/sites/{tenant}.sharepoint.com:/sites/{site}
```

Look for the `id` field in the response.

**Via PowerShell:**

```powershell
Connect-PnPOnline -Url "https://{tenant}.sharepoint.com/sites/your-site"
Get-PnPSite -Includes Id | Select-Object Id
```

### Finding Subsite Compound IDs

Subsites use a compound site ID format (`hostname,siteCollectionId,webId`) instead of a plain UUID. To find a subsite's compound ID:

**Via Microsoft Graph Explorer:**

```
GET https://graph.microsoft.com/v1.0/sites/{tenant}.sharepoint.com:/sites/{parentSite}/{subsiteName}
```

The `id` field in the response is the compound ID:

```json
{
  "id": "contoso.sharepoint.com,a1b2c3d4-...,e5f6a7b8-..."
}
```

Use this full value as the `siteId` in your site configuration.

**Via PowerShell:**

```powershell
Connect-PnPOnline -Url "https://{tenant}.sharepoint.com/sites/{parentSite}/{subsiteName}"
Get-PnPSite -Includes Id, Url | Select-Object Id, Url
```

**Via Browser (manual construction — discouraged):**

You can technically construct the compound ID by navigating to the subsite and calling two REST endpoints:

- `https://{tenant}.sharepoint.com/sites/{parentSite}/{subsiteName}/_api/site/id` → `siteCollectionId`
- `https://{tenant}.sharepoint.com/sites/{parentSite}/{subsiteName}/_api/web/id` → `webId`

Then combine as `{tenant}.sharepoint.com,{siteCollectionId},{webId}`. This approach is error-prone and discouraged — prefer Microsoft Graph Explorer or PowerShell instead.

**For nested subsites**, extend the path:

```
https://graph.microsoft.com/v1.0/sites/{tenant}.sharepoint.com:/sites/{parentSite}/{subsite}/{nestedSubsite}
```

## Subsites Scanning

### Overview

When `subsitesScan` is set to `enabled` for a site, the connector recursively discovers all subsites under that site and syncs their content alongside the parent site's content. This means you only need to configure the top-level site — all nested subsites are discovered and included automatically.

### How It Works

1. **Discovery** — During each sync cycle, the connector calls the Graph API (`GET /sites/{siteId}/sites`) to list direct child subsites, then recurses into each child to discover the full subsite tree.
2. **Content fetching** — For each discovered subsite, the connector fetches document libraries and site pages using the same `syncColumnName` as the parent site.
3. **Scope hierarchy** — Subsite content is ingested under the parent site's scope tree. Each subsite appears as a folder at its relative path within the hierarchy (e.g., `/RootScope/SubsiteA/Documents/file.pdf`).
4. **File diff** — Subsite items are keyed under the parent site's ID in the file-diff mechanism. If a subsite is later removed or reconfigured, its files are detected as deleted and cleaned up.

### Deduplication with Standalone Sites

If a subsite is also configured as a standalone site (using its compound site ID), it is **excluded** from the parent's recursive discovery to avoid double-syncing. The connector compares compound IDs across all configured sites and skips any match during discovery, including any further subsites.

### Limitations

- The `syncColumnName` is shared between the parent site and all its subsites. You cannot use a different sync column per subsite.
- Subsites are only addressable via compound site IDs (`hostname,siteCollectionId,webId`) in the Graph API. A plain UUID cannot identify a subsite.

### Configuring Document Libraries for Sync

#### Adding the Sync Column

1. Navigate to your SharePoint document library
2. Click **Add column** → **Yes/No**
3. Name the column (code default if unset: `FinanceGPTKnowledge`)
4. Set default value to **No**
5. Click **Save**

#### Column Settings

- **Column name**: Must match the `syncColumnName` configured for the site in the tenant configuration YAML or SharePoint configuration list
- **Type**: Yes/No (Boolean)
- **Default value**: No (recommended)
- **Require this column**: No

**Important — Column Renaming:** SharePoint distinguishes between a column's **internal name** (set at creation time and immutable) and its **display name** (which can be changed later). The Microsoft Graph API returns items using the internal name. If you rename a sync column in the SharePoint UI, only the display name changes — the internal name used by the API remains the original value. The `syncColumnName` in the connector configuration must match the **internal name**, not the current display name. If a column was created as `UniqueAI` and later renamed to `SyncToUnique`, the connector must still use `UniqueAI`. It is recommended to create a new column with desired name instead of renaming to avoid confusion in the future.

#### User Workflow

Users mark documents for sync by:

1. Selecting a document in the library
2. Clicking the sync column
3. Setting value to **Yes**

The connector picks up flagged files on the next scan cycle.

## Processing Configuration

The `processing` section of the tenant configuration file controls file processing behavior:

```yaml
processing:
  stepTimeoutSeconds: 30
  concurrency: 1
  maxFileSizeToIngestBytes: 209715200
  allowedMimeTypes:
    - application/pdf
    - text/plain
    - text/html
    - application/x-asp
    - application/vnd.openxmlformats-officedocument.wordprocessingml.document
    - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - application/vnd.openxmlformats-officedocument.presentationml.presentation
  scanIntervalCron: "*/15 * * * *"
```

| Option                     | Default                     | Description                                                                                                                              |
| -------------------------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `stepTimeoutSeconds`       | `30`                        | Time limit (in seconds) for a single file processing step before the file is skipped                                                     |
| `concurrency`              | `1`                         | Number of files to ingest into Unique concurrently                                                                                       |
| `maxFileSizeToIngestBytes` | `209715200` (200 MB)        | Maximum file size in bytes. Files larger than this are skipped with a warning in the logs                                                |
| `allowedMimeTypes`         | (none — must be configured) | List of MIME types the connector will process. The Helm chart ships sensible defaults; see [Supported File Types](#Supported-File-Types) |
| `scanIntervalCron`         | `*/15 * * * *`              | Cron expression for the scheduled sync interval                                                                                          |

## Supported File Types

Configure allowed types via the `allowedMimeTypes` processing option. There is no schema-level default — operators must explicitly configure this field. The Helm chart ships the following defaults:

| Extension      | MIME Type                                                                   | Helm Default |
| -------------- | --------------------------------------------------------------------------- | ------------ |
| `.pdf`         | `application/pdf`                                                           | Yes          |
| `.docx`        | `application/vnd.openxmlformats-officedocument.wordprocessingml.document`   | Yes          |
| `.xlsx`        | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`         | Yes          |
| `.pptx`        | `application/vnd.openxmlformats-officedocument.presentationml.presentation` | Yes          |
| `.txt`         | `text/plain`                                                                | Yes          |
| `.html`        | `text/html`                                                                 | Yes          |
| `.asp`/`.aspx` | `application/x-asp`                                                         | Yes          |

**Note:** `.aspx` SharePoint pages bypass the MIME type filter and are always eligible for ingestion regardless of `allowedMimeTypes`.

## Scheduler Configuration

### Sync Interval

The connector runs sync cycles at regular intervals, controlled by `scanIntervalCron` in the `processing` section of the tenant configuration file:

```yaml
processing:
  scanIntervalCron: "*/15 * * * *" # Default: every 15 minutes
```

**Considerations:**

- Lower intervals increase API usage and may hit rate limits
- Higher intervals delay sync of new content
- Recommended range: every hour, every night

## Logging

### Application Logs

The connector produces structured JSON logs:

```json
{
  "timestamp": "2024-01-15T10:30:00.000Z",
  "level": "info",
  "message": "Sync cycle started",
  "traceId": "abc123",
  "siteId": "xxx-xxx-xxx"
}
```

### Log Levels

| Level   | Description                     |
| ------- | ------------------------------- |
| `debug` | Detailed debugging information  |
| `info`  | General operational information |
| `warn`  | Warning conditions              |
| `error` | Error conditions                |

### Audit Logs

Audit events are logged for compliance:

- Sync cycle start/end
- Files processed (create, update, delete)
- Permission changes
- Authentication events
- Configuration changes

## Metrics

### System Telemetry

Standard Kubernetes metrics are exposed:

- CPU usage
- Memory usage
- Pod restarts
- Network I/O

### Application Telemetry

All custom metrics use the `spc_` prefix (SharePoint Connector).

#### Sync Cycle Metrics

| Metric                      | Type      | Labels                              | Description                                                 |
| --------------------------- | --------- | ----------------------------------- | ----------------------------------------------------------- |
| `spc_sync_duration_seconds` | Histogram | `sync_type`, `sp_site_id`, `result` | Duration of synchronization cycles (per site and full sync) |

Histogram buckets: 10s, 30s, 60s, 5m, 10m, 30m, 1h

#### File Processing Metrics

| Metric                               | Type    | Labels                              | Description                                                         |
| ------------------------------------ | ------- | ----------------------------------- | ------------------------------------------------------------------- |
| `spc_ingestion_file_processed_total` | Counter | `sp_site_id`, `step_name`, `result` | Files processed by ingestion pipeline steps                         |
| `spc_file_diff_events_total`         | Counter | `sp_site_id`, `diff_result_type`    | File change detection events (`new`, `updated`, `moved`, `deleted`) |
| `spc_file_moved_total`               | Counter | `sp_site_id`, `result`              | File move operations in Unique                                      |
| `spc_file_deleted_total`             | Counter | `sp_site_id`, `result`              | File deletion operations in Unique                                  |

#### Microsoft Graph API Metrics

| Metric                                      | Type      | Labels                                                      | Description                                   |
| ------------------------------------------- | --------- | ----------------------------------------------------------- | --------------------------------------------- |
| `spc_ms_graph_api_request_duration_seconds` | Histogram | `ms_tenant_id`, `api_method`, `result`, `http_status_class` | Request latency for Microsoft Graph API calls |
| `spc_ms_graph_api_throttle_events_total`    | Counter   | `ms_tenant_id`, `api_method`, `policy`                      | Microsoft Graph API throttling (429) events   |
| `spc_ms_graph_api_slow_requests_total`      | Counter   | `ms_tenant_id`, `api_method`, `duration_bucket`             | Slow Microsoft Graph API requests             |

Request duration histogram buckets: 100ms, 500ms, 1s, 2s, 5s, 10s, 20s

Slow request `duration_bucket` values: `>1s`, `>2s`, `>5s`, `>10s`

#### Unique API Metrics

| Metric                                            | Type      | Labels                                      | Description                                  |
| ------------------------------------------------- | --------- | ------------------------------------------- | -------------------------------------------- |
| `spc_unique_graphql_api_request_duration_seconds` | Histogram | `api_method`, `result`, `http_status_class` | Request latency for Unique GraphQL API calls |
| `spc_unique_graphql_api_slow_requests_total`      | Counter   | `api_method`, `duration_bucket`             | Slow Unique GraphQL API calls                |
| `spc_unique_rest_api_request_duration_seconds`    | Histogram | `api_method`, `result`, `http_status_class` | Request latency for Unique REST API calls    |
| `spc_unique_rest_api_slow_requests_total`         | Counter   | `api_method`, `duration_bucket`             | Slow Unique REST API calls                   |

Request duration histogram buckets: 100ms, 500ms, 1s, 2s, 5s, 10s, 20s

#### Permissions Sync Metrics

| Metric                                         | Type      | Labels                    | Description                                                       |
| ---------------------------------------------- | --------- | ------------------------- | ----------------------------------------------------------------- |
| `spc_permissions_sync_duration_seconds`        | Histogram | `sp_site_id`, `result`    | Duration of the permissions synchronization phase for a site      |
| `spc_permissions_sync_group_operations_total`  | Counter   | `sp_site_id`, `operation` | Operations performed on SharePoint groups during permissions sync |
| `spc_permissions_sync_folder_operations_total` | Counter   | `sp_site_id`, `operation` | Folder (scope) permission changes synced (`added`, `removed`)     |
| `spc_permissions_sync_file_operations_total`   | Counter   | `sp_site_id`, `operation` | File permission changes synced (`added`, `removed`)               |

Permissions sync duration histogram buckets: 5s, 10s, 30s, 60s, 2m, 5m, 10m, 30m

### Grafana Dashboard

A Grafana dashboard template is available in the Helm chart:

```yaml
grafana:
  dashboard:
    enabled: true
    folder: connectors
```

### Alerts

#### Default Alert Categories

The Helm chart organizes alerts into three categories, each independently toggleable:

| Category    | Alert Name                           | Description                      |
| ----------- | ------------------------------------ | -------------------------------- |
| `graphql`   | `SharepointConnectorGraphQLErrors`   | GraphQL API error rate alert     |
| `uniqueApi` | `SharepointConnectorUniqueAPIErrors` | Unique REST API error rate alert |
| `syncs`     | `SharepointConnectorSyncFailures`    | Sync cycle failure alert         |

Each category supports `enabled`, `disabled` (per-alert), and `customRules` (to override `for`, `severity`, `threshold`).

#### Custom Alerts

```yaml
alerts:
  enabled: true
  rules:
    - alert: LongSyncCycle
      expr: histogram_quantile(0.95, rate(spc_sync_duration_seconds_bucket[5m])) > 3600
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Sync cycle taking too long"
```

## Complete Re-ingestion

To perform a complete re-ingestion of all synced SharePoint content:

### Prerequisites

- Access to Unique API or admin interface
- Ability to pause the connector

### Step 1: Pause the SharePoint Connector

Scale down the deployment:

```bash
kubectl scale deployment sharepoint-connector --replicas=0 -n sharepoint-connector
```

### Step 2: Delete Root Scope and All Content

Use the Unique Public API to delete content recursively starting from the root scope. This removes all synced content.

**Warning:** This operation is irreversible. Ensure you have backups if needed.

### Step 3: Re-enable the Connector

Scale up the deployment:

```bash
kubectl scale deployment sharepoint-connector --replicas=1 -n sharepoint-connector
```

The connector will perform a full sync on the next cycle, re-ingesting all flagged content.

### Further Guidance

A dedicated re-ingestion runbook with extended prerequisites, API request examples, and operational caveats will be linked here in a later documentation update.
