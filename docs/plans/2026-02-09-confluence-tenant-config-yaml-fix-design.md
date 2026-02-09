# Design: Fix Confluence Tenant Config YAML Files

## Problem

The `local-tenant-config.yaml` in the confluence-connector was copied from the sharepoint-connector and contains SharePoint-specific configuration fields (`sharepoint`, `tenantId`, `sitesSource`, `sites`, `graphApiRateLimitPerMinuteThousands`, `allowedMimeTypes`, etc.) instead of Confluence-specific fields. This file does not validate against the Confluence tenant config schema.

Additionally, there are no example YAML files showing different Confluence configuration combinations, making it harder for operators to set up new tenant configs.

## Solution

### Overview

Replace the SharePoint-format YAML with correct Confluence-format YAML across 3 files. The tenant config schema has three sections: `confluence`, `unique`, and `processing`. No changes to the loader or schemas are needed — only the YAML files.

### Files

1. **`src/tenant-configs/local-tenant-config.yaml`** — Local development config
   - Confluence Cloud with `api_token` auth
   - External Unique auth (Zitadel) pointing to localhost
   - Conservative processing settings with `maxPagesToScan` limit for testing

2. **`src/tenant-configs/example-cloud-tenant-config.yaml`** — Production-like cloud example
   - Confluence Cloud with `api_token` auth
   - External Unique auth (Zitadel) with placeholder URLs
   - Higher concurrency, no page scan limit
   - Commented-out `ingestionConfig` showing optional capabilities

3. **`src/tenant-configs/example-onprem-tenant-config.yaml`** — On-prem example
   - Confluence Data Center with `pat` auth
   - Cluster-local Unique auth with `serviceExtraHeaders`
   - Different processing settings (longer timeout, 2-hour cron)

### Key Differences from SharePoint Config

| SharePoint Field | Confluence Equivalent |
|---|---|
| `sharepoint.tenantId` | Not applicable |
| `sharepoint.auth.mode: certificate` | `confluence.auth.mode: api_token / pat / basic` |
| `sharepoint.sitesSource` | Not applicable (uses labels instead) |
| `sharepoint.sites[]` | Not applicable |
| `sharepoint.graphApiRateLimitPerMinuteThousands` | `confluence.apiRateLimitPerMinute` |
| `processing.allowedMimeTypes` | Not applicable |
| `processing.maxFileSizeToIngestBytes` | Not applicable |
| `processing.maxFilesToScan` | `processing.maxPagesToScan` |

### Configuration Schema Reference

**Confluence section:**
- `instanceType`: `cloud` or `onprem`
- `baseUrl`: Instance URL without trailing slash
- `auth`: Discriminated union on `mode` — `api_token` (email + apiToken), `pat` (token), or `basic` (username + password)
- `apiRateLimitPerMinute`: Rate limit (default: 100)
- `ingestSingleLabel`: Label for single-page sync (default: `ai-ingest`)
- `ingestAllLabel`: Label for full sync (default: `ai-ingest-all`)

**Unique section:** Same as SharePoint — `cluster_local` or `external` auth mode with service URLs.

**Processing section:**
- `stepTimeoutSeconds` (default: 300)
- `concurrency` (default: 1)
- `scanIntervalCron` (default: `*/15 * * * *`)
- `maxPagesToScan` (optional, for testing)

## Out of Scope

- Multi-tenant loader changes (separate PR)
- Schema modifications
- Helm chart template updates

## Tasks

1. **Fix local-tenant-config.yaml** — Replace SharePoint fields with Confluence Cloud + api_token + External Zitadel auth config matching the schema.
2. **Create example-cloud-tenant-config.yaml** — Cloud example with api_token auth, external Unique auth, production-like settings, and inline documentation comments.
3. **Create example-onprem-tenant-config.yaml** — On-prem example with PAT auth, cluster-local Unique auth, and different processing settings.
