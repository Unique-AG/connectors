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
| `HEALTH_SYNC_HISTORY_SIZE`            | `5`                                               | Number of recent sync runs kept in the sliding window for health evaluation                                          |
| `HEALTH_SYNC_SITE_FAILURE_THRESHOLD`  | `0.5`                                             | Per-site failure ratio (0–1) across the window that marks the service unhealthy when exceeded                        |
| `HEALTH_CONNECTIVITY_TIMEOUT_MS`      | `3000`                                            | Timeout in milliseconds for each reachability ping used by the health endpoint                                       |

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

  # Deployment-wide defaults applied to every site below; per-site values
  # win when set. See "Site Defaults" further down for full semantics.
  siteDefaults:
    syncColumnName: FinanceGPTKnowledge
    storeInternally: enabled
    syncStatus: active
    syncMode: content_only
    permissionsInheritanceMode: inherit_scopes_and_files

  sitesSource: config_file
  sites:
    # Overrides syncMode for this site; everything else inherits from siteDefaults.
    - siteId: 12345678-1234-1234-1234-123456789abc
      ingestionMode: recursive
      scopeId: scope_bu4gokr0atzj0kfiuaaaaaaa
      maxFilesToIngest: 1000
      syncMode: content_and_permissions
    # Overrides syncColumnName for this site; everything else inherits from siteDefaults.
    - siteId: 87654321-4321-4321-4321-cba987654321
      syncColumnName: HRKnowledge
      ingestionMode: flat
      scopeId: scope_bu4gokr0atzj0kfiubbbbbb
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

You can use [the CSV import template](./sites-to-sync-template.csv) when populating the SharePoint list for `sharepoint_list`-based configuration.

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

| Option                                | Required | Default | Description                                                                                       |
| ------------------------------------- | -------- | ------- | ------------------------------------------------------------------------------------------------- |
| `tenantId`                            | Yes      | —       | Azure AD tenant ID                                                                                |
| `baseUrl`                             | Yes      | —       | Company SharePoint URL (e.g., `https://acme.sharepoint.com`). Must not end with a trailing slash  |
| `graphApiRateLimitPerMinuteThousands` | No       | `780`   | Microsoft Graph API rate limit in thousands of requests per minute                                |
| `auth`                                | Yes      | —       | Authentication configuration (see [Authentication](#Authentication))                              |
| `siteDefaults`                        | No       | `{}`    | Deployment-level fallbacks applied to every per-site config (see [Site Defaults](#Site-Defaults)) |

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

| Mode                | Description                          |
| ------------------- | ------------------------------------ |
| `none`              | Proxy disabled (default)             |
| `no_auth`           | Proxy enabled without authentication |
| `username_password` | Basic authentication proxy           |
| `ssl_tls`           | TLS client certificate proxy         |

**Common options** (required for `no_auth`, `username_password`, and `ssl_tls` modes):

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

When using `sharepoint_list` as the sites source, create a SharePoint list with the following columns. Only `siteId` is strictly required as a column on the list — any other column whose value is set via [Site Defaults](#Site-Defaults) can be omitted from the list entirely, and rows will inherit the deployment-wide value.

| Column Display Name          | Type             | Description                                                                                                       |
| ---------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------------- |
| `siteId`                     | Single line text | SharePoint site ID (UUID or compound format: `hostname,siteCollectionId,webId` for subsites)                      |
| `syncColumnName`             | Single line text | Column that marks files for sync                                                                                  |
| `ingestionMode`              | Choice           | `flat` or `recursive`                                                                                             |
| `uniqueScopeId`              | Single line text | Unique scope ID. Either `scope_<id>` (existing root) or `in_parent:scope_<parentId>` (auto-resolve under parent). |
| `maxFilesToIngest`           | Number           | Maximum new + updated files per sync cycle; sync fails for the site if exceeded                                   |
| `storeInternally`            | Choice           | `enabled` or `disabled`                                                                                           |
| `syncStatus`                 | Choice           | `active`, `inactive`, or `deleted`                                                                                |
| `syncMode`                   | Choice           | `content_only` or `content_and_permissions`                                                                       |
| `permissionsInheritanceMode` | Choice           | Optional inheritance mode                                                                                         |
| `subsitesScan`               | Choice           | `enabled` or `disabled` (default: `disabled`)                                                                     |

### Benefits of SharePoint List Configuration

- **Self-service**: Site owners can request sync without IT involvement
- **No redeployment**: Add/modify sites without restarting the connector
- **Audit trail**: SharePoint tracks changes to the configuration list
- **Approval workflows**: Use SharePoint approval flows for governance

## Per-Site Configuration Options

**Important:** The connector is a singleton — each SharePoint site must be configured in at most one connector process per Unique instance. Configuring the same site in multiple processes leads to conflicting state and unexpected behavior of the connector.

| Option                       | Values                                                                | Default                    | Description                                                                                                                                                    |
| ---------------------------- | --------------------------------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `siteId`                     | UUID or compound ID                                                   | — (required)               | SharePoint site ID. Subsites use compound format: `hostname,siteCollectionId,webId`                                                                            |
| `syncColumnName`             | String                                                                | `FinanceGPTKnowledge`      | Display name or internal name of the sync flag column (display name takes priority)                                                                            |
| `ingestionMode`              | `flat`, `recursive`                                                   | — (required)               | Flat ingests all to one scope; recursive maintains hierarchy                                                                                                   |
| `scopeId`                    | `scope_<id>` or `in_parent:scope_<parentId>`                          | — (required)               | Where to mount this site's content, see [Choosing between fixed scope and `in_parent:` auto-resolve](#Choosing-between-fixed-scope-and-in_parent-auto-resolve) |
| `maxFilesToIngest`           | Number                                                                | — (unlimited)              | Maximum new + updated files per sync cycle; sync fails for the site if exceeded                                                                                |
| `storeInternally`            | `enabled`, `disabled`                                                 | `enabled`                  | Whether to store content in Unique                                                                                                                             |
| `syncStatus`                 | `active`, `inactive`, `deleted`                                       | `active`                   | Control sync behavior                                                                                                                                          |
| `syncMode`                   | `content_only`, `content_and_permissions`                             | — (required)               | What to sync                                                                                                                                                   |
| `permissionsInheritanceMode` | `none`, `inherit_files`, `inherit_scopes`, `inherit_scopes_and_files` | `inherit_scopes_and_files` | Inheritance settings for content_only, see [Permissions Inheritance Modes](#Permissions-Inheritance-Modes) mode                                                |
| `subsitesScan`               | `enabled`, `disabled`                                                 | `disabled`                 | Recursively discover and sync content from subsites                                                                                                            |

### Choosing between fixed scope and `in_parent:` auto-resolve

**Fixed (`scope_<id>`)** — each site needs its own scope, pre-created by the operator before the site is configured. Best when scopes are managed centrally and named or permissioned individually, since the operator stays in full control of the scope's identity, ACLs, and lifecycle.

**Auto (`in_parent:scope_<parentId>`)** — the connector finds-or-creates a child scope under the parent on every sync, named after the SharePoint site's URL slug. Removing a site (via `syncStatus: deleted`) removes the auto-created scope. If a sibling scope under the parent already has the same site name and isn't claimed by us, the connector aborts the sync with a typed error rather than guessing to stay on the safe side and not sync a site into a user folder.

### Permissions Inheritance Modes

Only used when `syncMode` is `content_only`. It controls whether newly created scopes / files inherit permissions from their parent. If scopes / files are configured to not inherit permissions, any newly created scopes / files will not be visible to platform users, only to service user. To grant access to these new scopes / files, admin has to use API on behalf of the service user.

| Mode                       | Scopes Inherit | Files Inherit |
| -------------------------- | -------------- | ------------- |
| `inherit_scopes_and_files` | Yes            | Yes           |
| `inherit_scopes`           | Yes            | No            |
| `inherit_files`            | No             | Yes           |
| `none`                     | No             | No            |

## Site Defaults

`sharepoint.siteDefaults` lets you set deployment-level fallbacks for any per-site option except `siteId`. Each site (whether sourced from `config_file` or from a `sharepoint_list` row) is merged with the defaults: if the per-site value is set, it wins; otherwise the default is used. This keeps individual site entries terse and makes it easy to change a policy across an entire deployment in one place.

### With `config_file`

```yaml
sharepoint:
  # ... auth and base configuration ...

  siteDefaults:
    syncColumnName: FinanceGPTKnowledge
    ingestionMode: recursive
    storeInternally: enabled
    syncStatus: active
    syncMode: content_only
    permissionsInheritanceMode: inherit_scopes_and_files
    subsitesScan: disabled

  sitesSource: config_file
  sites:
    # Inherits everything from siteDefaults except scopeId / maxFilesToIngest
    - siteId: 12345678-1234-1234-1234-123456789abc
      scopeId: scope_bu4gokr0atzj0kfiuaaaaaaa
      maxFilesToIngest: 1000
    # Overrides syncColumnName and ingestionMode for this site
    - siteId: 87654321-4321-4321-4321-cba987654321
      syncColumnName: HRKnowledge
      ingestionMode: flat
      scopeId: scope_bu4gokr0atzj0kfiubbbbbb
```

### With `sharepoint_list`

`siteDefaults` works identically for `sharepoint_list`: any column whose value is set on a row wins; any column that is blank (or whose mapped field is `undefined` because the column is not present on the list at all) falls back to the default. This means **columns covered by `siteDefaults` can be omitted from the SharePoint list entirely** — only the columns you want to vary per row need to exist. At minimum, the list must carry `siteId`; everything else can live in `siteDefaults`.

```yaml
sharepoint:
  # ... auth and base configuration ...

  siteDefaults:
    syncColumnName: FinanceGPTKnowledge
    ingestionMode: recursive
    storeInternally: enabled
    syncStatus: active
    syncMode: content_only
    permissionsInheritanceMode: inherit_scopes_and_files
    subsitesScan: disabled
    # Common pattern: every site auto-creates a child under one shared parent scope,
    # so the list does not need a `uniqueScopeId` column at all.
    scopeId: in_parent:scope_bu4gokr0atzj0kfiucccccc

  sitesSource: sharepoint_list
  sharepointList:
    siteId: your-config-site-id-here
    listId: 00000000-0000-0000-0000-000000000000
```

With the example above, the SharePoint list can be reduced to a single `siteId` column — every other per-site field is supplied by `siteDefaults`. Add columns back to the list only when you need per-site overrides for those fields.

### Merge Rules

- **Per-site value wins when "set".** For string-typed fields (including `siteId`, `scopeId`, `syncColumnName`), "set" means non-`undefined` and non-empty after trim — so a blank cell in a SharePoint list row falls back to the default. For numeric/enum fields, any non-`undefined` value counts as set.
- **Required-after-merge.** `ingestionMode`, `scopeId`, and `syncMode` are required on the final merged config. If a per-site entry omits them and `siteDefaults` does not supply them either, the merger throws — and because sites are merged eagerly at the start of every sync cycle (for both `config_file` and `sharepoint_list`), a single unmergeable row aborts the **entire sync cycle**, not just that site. The service stays running and retries on the next scheduled cycle; the failure is recorded as a full-sync failure with step `SitesConfigLoading`.
- **`siteId` cannot be defaulted.** It must always be set per site.

### Schema Defaults

The fields below have schema-level defaults applied even when you do not provide a `siteDefaults` block. Listing them in `siteDefaults` is still allowed if you want to make them explicit, but it is optional.

| Field                        | Schema Default             |
| ---------------------------- | -------------------------- |
| `syncColumnName`             | `FinanceGPTKnowledge`      |
| `storeInternally`            | `enabled`                  |
| `syncStatus`                 | `active`                   |
| `permissionsInheritanceMode` | `inherit_scopes_and_files` |
| `subsitesScan`               | `disabled`                 |

The remaining defaultable fields (`ingestionMode`, `scopeId`, `maxFilesToIngest`, `syncMode`) have no schema default — they take effect only if you set them under `siteDefaults` or per site.

## SharePoint Site Configuration

### Finding SharePoint Site IDs

Site IDs are required to configure which SharePoint sites the connector scans. The connector supports both `/sites/` and `/teams/` managed paths.

**Via Browser:**

Navigate to: `https://{tenant}.sharepoint.com/sites/your-site/_api/site/id` (or `/teams/your-team/_api/site/id` for team sites)

The response will be XML containing the site ID:

```xml
<d:Id>12345678-1234-1234-1234-123456789012</d:Id>
```

**Via Microsoft Graph Explorer:**

```
GET https://graph.microsoft.com/v1.0/sites/{tenant}.sharepoint.com:/sites/{site}
```

For team sites, use `/teams/` instead of `/sites/`:

```
GET https://graph.microsoft.com/v1.0/sites/{tenant}.sharepoint.com:/teams/{team}
```

Look for the `id` field in the response.

**Via PowerShell:**

```powershell
Connect-PnPOnline -Url "https://{tenant}.sharepoint.com/sites/your-site"
Get-PnPSite -Includes Id | Select-Object Id
```

For team sites, replace `/sites/` with `/teams/` in the URL.

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

**Column name resolution:** SharePoint distinguishes between a column's **internal name** (set at creation time and immutable) and its **display name** (which can be changed later in the UI). The connector accepts either name in the `syncColumnName` configuration and resolves it per drive/list as follows:

1. If a column's **display name** matches `syncColumnName`, the connector uses that column's internal name for filtering.
2. Otherwise, if a column's **internal name** matches `syncColumnName`, that name is used directly.
3. If neither matches, the drive or SitePages list is **skipped entirely** — the connector logs a warning and moves on to the next drive without scanning any items.

This means you can configure `syncColumnName` using the human-readable display name shown in the SharePoint UI (e.g., `Sync to Unique`) even if the underlying internal name is different (e.g., `Sync_Unique`). When a display name is resolved to a different internal name, the connector logs the mapping for transparency.

**Note on column renaming:** If a column was created as `UniqueAI` and later renamed to `SyncToUnique` in the UI, only the display name changes — the internal name remains `UniqueAI`. You can configure `syncColumnName` as either `SyncToUnique` (the current display name) or `UniqueAI` (the internal name). Using the display name is recommended as it is easier to verify in the SharePoint UI, but please be aware of this behavior in case of conflicts.

#### Drive and List Skipping

The connector checks each document library (drive) and the SitePages list for the presence of the configured sync column before scanning. If the column is not found on a drive, the entire drive is skipped — no items are fetched. This avoids unnecessary API calls for libraries that were never set up for sync. A warning is logged for each skipped drive so operators can verify the configuration.

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
    - application/vnd.openxmlformats-officedocument.wordprocessingml.document
    - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
    - application/vnd.openxmlformats-officedocument.presentationml.presentation
    - application/x-asp
    - text/plain
    - text/html
    - text/csv
  mimeTypeOverridesByExtension:
    .csv: text/csv
  scanIntervalCron: "*/15 * * * *"
```

| Option                         | Default                     | Description                                                                                                                              |
| ------------------------------ | --------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `stepTimeoutSeconds`           | `30`                        | Time limit (in seconds) for a single file processing step before the file is skipped                                                     |
| `concurrency`                  | `1`                         | Number of files to ingest into Unique concurrently                                                                                       |
| `maxFileSizeToIngestBytes`     | `209715200` (200 MB)        | Maximum file size in bytes. Files larger than this are skipped with a warning in the logs                                                |
| `allowedMimeTypes`             | (none — must be configured) | List of MIME types the connector will process. The Helm chart ships sensible defaults; see [Supported File Types](#Supported-File-Types) |
| `mimeTypeOverridesByExtension` | `{ .csv: text/csv }`        | Map of file extension suffix to canonical MIME type. See [MIME Type Overrides by Extension](#MIME-Type-Overrides-by-Extension)           |
| `scanIntervalCron`             | `*/15 * * * *`              | Cron expression for the scheduled sync interval                                                                                          |

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
| `.csv`         | `text/csv`                                                                  | Yes          |

**Note:** `.aspx` SharePoint pages bypass the MIME type filter and are always eligible for ingestion regardless of `allowedMimeTypes`.

## MIME Type Overrides by Extension

SharePoint occasionally reports the wrong MIME type for a file (notably `.csv` files come back as `application/vnd.ms-excel`). This causes the ingestion service to reject the file even when the operator has whitelisted the correct type. The `mimeTypeOverridesByExtension` map rewrites the SharePoint-reported MIME type by file extension before the allow-list check runs, so both the filter and the registered content carry the canonical value.

```yaml
processing:
  mimeTypeOverridesByExtension:
    .csv: text/csv
```

**Defaults and merging:** The default value is `{ .csv: text/csv }`. A user-supplied value **replaces the default wholesale** — there is no merge. To keep the CSV fix while adding your own overrides, include `.csv: text/csv` explicitly in your map.

**Suffix matching:** Keys are matched against the lowercased file name with `endsWith`. Both keys and file names are lowercased, so `.CSV` and `Foo.Csv` match a `.csv` key. Multi-segment suffixes are supported (e.g. `.tar.gz`); when multiple keys could match (e.g. `.tar.gz` and `.gz` are both configured), the **longest match wins** — so `archive.tar.gz` resolves via `.tar.gz`, not `.gz`.

**Validation:** Keys must match `^(\.[a-z0-9]+)+$` after lowercase normalization (one or more `.alphanumeric` segments). Empty MIME values are rejected. Invalid configuration fails fast at startup.

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

## Health Endpoint

The connector exposes a `GET /health` endpoint that reports operational health. It is separate from the existing `GET /probe` endpoint used for K8s liveness/readiness probes — `GET /health` is intended for external monitoring and SRE tooling.

The endpoint returns HTTP `200` when all checks pass and HTTP `503` when any check fails. The response follows the `@nestjs/terminus` format with `status`, `info`, `error`, and `details` fields.

### Health Checks

The endpoint runs three checks on every request:

**Sync** — Evaluates sync history from a sliding window of the last N runs (configurable via `HEALTH_SYNC_HISTORY_SIZE`). Each site's failure ratio is computed independently: `failures / appearances`. If any site exceeds `HEALTH_SYNC_SITE_FAILURE_THRESHOLD`, the check is `down`. When no sync has completed yet (e.g. shortly after startup), this check is omitted from the response. A single transient per-site failure is absorbed by the window and does not trigger an alert.

**Connectivity** — Performs unauthenticated HTTP requests to Microsoft Graph (`https://graph.microsoft.com/v1.0/`) and the configured SharePoint base URL. Any HTTP response (including 401/403) proves the endpoint is reachable — only transport-level failures (DNS, TLS, timeout, connection refused) are treated as unhealthy.

**Unique API** — Sends a minimal `{ __typename }` GraphQL query to both Unique API endpoints (ingestion and scope management). Unlike the connectivity check, non-2xx responses (401/403/500) are treated as unhealthy because they indicate the API is not functioning correctly. These requests bypass the internal rate limiter to avoid queuing behind sync traffic.

### Response Examples

**Healthy (200):**

```json
{
  "status": "ok",
  "info": {
    "sync": {
      "status": "up",
      "lastSyncAt": "2026-03-18T10:15:00.000Z",
      "recentSyncs": 5,
      "sites": {
        "site-aaa": { "failures": 0, "total": 5 },
        "site-bbb": { "failures": 1, "total": 5 }
      }
    },
    "connectivity": {
      "status": "up",
      "graph": "reachable",
      "sharepoint": [
        { "tenant": "default", "status": "reachable" }
      ]
    },
    "uniqueApi": {
      "status": "up",
      "ingestion": "reachable",
      "scopeManagement": "reachable"
    }
  },
  "error": {},
  "details": { "...same as info when healthy..." }
}
```

**Unhealthy (503) — site exceeds sync failure threshold:**

```json
{
  "status": "error",
  "info": {
    "connectivity": { "status": "up", "..." : "..." },
    "uniqueApi": { "status": "up", "..." : "..." }
  },
  "error": {
    "sync": {
      "status": "down",
      "lastSyncAt": "2026-03-18T10:15:00.000Z",
      "threshold": 0.5,
      "failingSites": ["site-bbb"],
      "sites": {
        "site-aaa": { "failures": 0, "total": 5 },
        "site-bbb": { "failures": 4, "total": 5 }
      }
    }
  },
  "details": { "...all checks combined..." }
}
```

### Configuration

| Variable                             | Default | Description                                                              |
| ------------------------------------ | ------- | ------------------------------------------------------------------------ |
| `HEALTH_SYNC_HISTORY_SIZE`           | `5`     | Number of recent sync runs in the sliding window                         |
| `HEALTH_SYNC_SITE_FAILURE_THRESHOLD` | `0.5`   | Per-site failure ratio (0–1) that triggers unhealthy when exceeded       |
| `HEALTH_CONNECTIVITY_TIMEOUT_MS`     | `3000`  | Timeout in milliseconds for each reachability ping (connectivity checks) |

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
