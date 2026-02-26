<!-- confluence-page-id: 1953824805 -->
<!-- confluence-space-key: PUBDOC -->


## Configuration Overview

The SharePoint Connector uses a **YAML-based tenant configuration file** for all settings. The configuration file path is specified via the `TENANT_CONFIG_PATH_PATTERN` environment variable.

## Configuration Sources

Sites can be configured in two ways:

| Source | Description | Use Case |
|--------|-------------|----------|
| `config_file` | Static YAML configuration | Simple deployments, fixed site list |
| `sharepoint_list` | Dynamic configuration from SharePoint list | Self-service, frequent changes |

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
    listDisplayName: SharePoint Sites to Sync
```

You can use [the CSV import template](./Template [env-name] Sites to Sync to Unique.csv) when populating the SharePoint list for `sharepoint_list`-based configuration.

## SharePoint List Configuration

When using `sharepoint_list` as the sites source, create a SharePoint list with the following columns:

| Column Display Name | Type | Description |
|---------------------|------|-------------|
| `siteId` | Single line text | SharePoint site ID (UUID) |
| `syncColumnName` | Single line text | Column that marks files for sync |
| `ingestionMode` | Choice | `flat` or `recursive` |
| `uniqueScopeId` | Single line text | Unique scope ID |
| `maxFilesToIngest` | Number | Optional limit per sync cycle |
| `storeInternally` | Choice | `enabled` or `disabled` |
| `syncStatus` | Choice | `active`, `inactive`, or `deleted` |
| `syncMode` | Choice | `content_only` or `content_and_permissions` |
| `permissionsInheritanceMode` | Choice | Optional inheritance mode |

### Benefits of SharePoint List Configuration

- **Self-service**: Site owners can request sync without IT involvement
- **No redeployment**: Add/modify sites without restarting the connector
- **Audit trail**: SharePoint tracks changes to the configuration list
- **Approval workflows**: Use SharePoint approval flows for governance

## Per-Site Configuration Options

| Option | Values | Description |
|--------|--------|-------------|
| `siteId` | UUID | SharePoint site ID |
| `syncColumnName` | String | Name of the sync flag column |
| `ingestionMode` | `flat`, `recursive` | Flat ingests all to one scope; recursive maintains hierarchy |
| `scopeId` | String | Root scope ID in Unique |
| `maxFilesToIngest` | Number | Optional limit per sync cycle |
| `storeInternally` | `enabled`, `disabled` | Whether to store content in Unique |
| `syncStatus` | `active`, `inactive`, `deleted` | Control sync behavior |
| `syncMode` | `content_only`, `content_and_permissions` | What to sync |
| `permissionsInheritanceMode` | See below | Inheritance settings (content_only mode) |

### Permissions Inheritance Modes

Only used when `syncMode` is `content_only`:

| Mode | Scopes Inherit | Files Inherit |
|------|----------------|---------------|
| `inherit_scopes_and_files` | Yes | Yes |
| `inherit_scopes` | Yes | No |
| `inherit_files` | No | Yes |
| `none` | No | No |

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

### Configuring Document Libraries for Sync

#### Adding the Sync Column

1. Navigate to your SharePoint document library
2. Click **Add column** → **Yes/No**
3. Name the column (default: `UniqueAI`)
4. Set default value to **No**
5. Click **Save**

#### Column Settings

- **Column name**: Must match `SHAREPOINT_SYNC_COLUMN_NAME` environment variable
- **Type**: Yes/No (Boolean)
- **Default value**: No (recommended)
- **Require this column**: No

#### User Workflow

Users mark documents for sync by:
1. Selecting a document in the library
2. Clicking the sync column
3. Setting value to **Yes**

The connector picks up flagged files on the next scan cycle.

## Supported File Types

The connector processes files based on MIME type. Configure allowed types via `ALLOWED_MIME_TYPES`:

| Extension | MIME Type | Default |
|-----------|-----------|---------|
| `.pdf` | `application/pdf` | Yes |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | Yes |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | Yes |
| `.pptx` | `application/vnd.openxmlformats-officedocument.presentationml.presentation` | Yes |
| `.txt` | `text/plain` | Yes |
| `.aspx` | `text/html` | Yes |

## Scheduler Configuration

### Sync Interval

The connector runs sync cycles at regular intervals:

```yaml
env:
  SYNC_INTERVAL_MINUTES: "15"  # Default: every 15 minutes
```

**Considerations:**

- Lower values increase API usage and may hit rate limits
- Higher values delay sync of new content
- Recommended range: every hour, every night

### Disabling Automatic Sync

For testing or maintenance:

```yaml
env:
  SYNC_ENABLED: "false"
```

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

| Level | Description |
|-------|-------------|
| `debug` | Detailed debugging information |
| `info` | General operational information |
| `warn` | Warning conditions |
| `error` | Error conditions |

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

Custom metrics for monitoring sync operations:

| Metric | Type | Description |
|--------|------|-------------|
| `sharepoint_sync_cycles_total` | Counter | Total sync cycles executed |
| `sharepoint_files_processed_total` | Counter | Files processed (by operation) |
| `sharepoint_sync_duration_seconds` | Histogram | Sync cycle duration |
| `sharepoint_api_requests_total` | Counter | API requests (by endpoint) |
| `sharepoint_api_errors_total` | Counter | API errors (by type) |

### Grafana Dashboard

A Grafana dashboard template is available in the Helm chart:

```yaml
grafana:
  dashboard:
    enabled: true
    folder: connectors
```

### Alerts

#### Default Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| SyncCycleFailed | Sync cycle errors > 3 | Warning |
| AuthenticationError | Auth failures > 0 | Critical |
| HighAPIErrorRate | API errors > 10% | Warning |
| SyncCycleStalled | No sync in 1 hour | Warning |

#### Custom Alerts

```yaml
alerts:
  enabled: true
  rules:
    - alert: LongSyncCycle
      expr: sharepoint_sync_duration_seconds > 3600
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
