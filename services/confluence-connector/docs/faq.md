<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## General

### What type of connector is this?

**Answer:** The Confluence Connector is a pull-based synchronization service that periodically scans Confluence spaces for labeled pages and syncs their content and attachments to the Unique knowledge base.

**Key characteristics:**

- Runs on a configurable cron schedule (default: every 15 minutes)
- Pulls content from Confluence via REST API
- Requires explicit labeling of pages to trigger synchronization
- Operates as a background service without user interaction
- Supports both Confluence Cloud and Confluence Data Center

### How does this differ from the Confluence Connector v1?

**Answer:**

| Aspect | v1 | v2 |
|---|---|---|
| Architecture | Monorepo module | Standalone service |
| Deployment | Part of a larger Node.js application | Independent Kubernetes container |
| Multi-tenancy | Not supported | Multiple Confluence instances in a single deployment |
| Attachment ingestion | Not supported | Supported with configurable extensions and size limits |
| Change detection | Re-ingests all content | File-diff mechanism ingests only new or modified items |
| Safety guards | None | Full-deletion prevention, concurrent sync prevention |
| Key format | `spaceId_spaceKey/pageId` | `tenantName/spaceId_spaceKey/pageId` (v1 format available via `useV1KeyFormat`) |

## Labels and Page Discovery

### How does the connector decide which pages to sync?

**Answer:** The connector uses two configurable Confluence labels: one for single-page sync (recommended: `ai-ingest`) and one for syncing a page and all its descendants (recommended: `ai-ingest-all`). Both labels must be explicitly set in the tenant configuration. See the [README](./README.md#core-capabilities) for a full overview of label-driven discovery and the [technical flows documentation](./technical/flows.md#discovery-phase) for the detailed CQL-based discovery process.

### What happens when a page has both labels?

**Answer:** The page is deduplicated. The connector merges all labeled pages and their descendants into a single unique set (by page ID), so no page is ingested twice.

### What happens when a page has `ai-ingest` and its ancestor has `ai-ingest-all`?

**Answer:** The page is discovered through both paths but deduplicated by ID, so it is ingested exactly once. See the [discovery flow](./technical/flows.md#discovery-sequence) for details on how deduplication works.

### Which Confluence content types are synced?

**Answer:** The connector ingests `page` and `blogpost` content (including Live Docs, which are a page subtype). Attachments are ingested conditionally when `attachments.mode=enabled`. Content types `database`, `whiteboard`, and `embed` are explicitly skipped because their APIs expose no renderable body. Folders have no body and are effectively skipped by the empty-body filter. Descendants of all non-skipped types (including skipped ones like databases) are still discovered and ingested when using `ai-ingest-all`. See the [Content Type Ingestion Map](./technical/flows.md#content-type-ingestion-map) for the full Cloud and Data Center breakdown.

### What format is the page content exported in?

**Answer:** Pages are fetched using the `body.storage` expansion, which returns the Confluence storage representation (HTML). The content is uploaded to Unique with MIME type `text/html`.

### Are Confluence labels preserved during ingestion?

**Answer:** Yes. All labels on a page are included as metadata during ingestion, except for the two connector labels (`ai-ingest` and `ai-ingest-all` by default), which are filtered out. The remaining labels are sorted alphabetically for deterministic ordering.

### Which spaces are scanned?

**Answer:** Only `global` spaces are scanned (Cloud also includes `collaboration` spaces). Personal spaces are excluded on both platforms. See the [Configuration Guide](./operator/configuration.md#space-scanning) for full details on space type filtering per instance type.

## Authentication

### What authentication methods are supported?

**Answer:** The connector supports OAuth 2.0 (2LO) for Confluence Cloud and Data Center (10.1+), which is the recommended authentication method. Personal Access Token (PAT) is supported only on Data Center versions below 10.1 where OAuth 2.0 (2LO) is not available, and is not recommended. Cloud instances support only OAuth 2.0 (2LO). See the [Authentication Guide](./operator/authentication.md) for full details on each method, credential setup, and token flows.

### How are secrets managed in configuration?

**Answer:** Secret values in tenant YAML configuration files use the `os.environ/VARIABLE_NAME` syntax to reference environment variables, resolved at startup. See [Authentication -- Secret Resolution](./operator/authentication.md#secret-resolution) for the full mechanism, supported fields, and Kubernetes integration.

## Configuration

### How are tenants configured?

**Answer:** Each tenant is configured via a YAML file following the naming convention `<tenant-name>-tenant-config.yaml`. The `TENANT_CONFIG_PATH_PATTERN` environment variable specifies a glob pattern to locate these files. Tenant names must match the pattern `^[a-z0-9]+(-[a-z0-9]+)*$` and must be unique across all config files. See the [Configuration Guide](./operator/configuration.md) for full details.

### What are the available tenant statuses?

**Answer:**

| Status | Behavior |
|---|---|
| `active` | Tenant is loaded and sync is scheduled (default if not specified) |
| `inactive` | Tenant config is validated but the tenant is not loaded |
| `deleted` | Tenant is skipped entirely |

At least one tenant must have `active` status for the connector to start.

### What are the key configuration sections?

**Answer:** Each tenant YAML file contains four top-level sections:

| Section | Purpose |
|---|---|
| `confluence` | Instance type, base URL, authentication, API rate limit, label names |
| `unique` | Unique API endpoints, authentication mode, rate limit |
| `processing` | Concurrency, cron schedule, optional scan limit |
| `ingestion` | Ingestion mode, scope ID, attachment settings, v1 key format toggle |

See the [Configuration Guide](./operator/configuration.md) for all available options and their defaults.

### What are the default values for key settings?

**Answer:**

| Setting | Default Value |
|---|---|
| Processing concurrency | 1 |
| Scan interval cron | `*/15 * * * *` (every 15 minutes) |
| Unique API rate limit | 100 requests/minute |
| Attachment ingestion | Enabled |
| Maximum attachment size | 200 MB |
| Store internally | Enabled |
| Use v1 key format | Disabled |

### What file extensions are allowed for attachments by default?

**Answer:** The default allowed extensions are pdf, docx, xlsx, ppt, pptx, txt, csv, and html. These can be overridden via `ingestion.attachments.allowedExtensions` (case-insensitive). See [Configuration -- Attachment Configuration](./operator/configuration.md#attachment-configuration) for the full details.

### How do I find my Atlassian Cloud ID?

**Answer:** The Cloud ID is required only for Confluence Cloud instances. You can find it by visiting:

```
https://your-domain.atlassian.net/_edge/tenant_info
```

The response contains a `cloudId` field with the UUID.

## Sync Behavior

### What happens during a sync cycle?

**Answer:** Each sync cycle follows these steps:

1. Grant the service account access to the pre-existing root scope in Unique and resolve its path (the root scope must be created by an administrator before the connector can use it)
2. Discover all pages matching the configured labels via CQL search
3. Fetch descendant pages for any pages with the all-descendants label
4. Extract allowed attachments from discovered pages
5. Compute a file diff per space against Unique's stored state
6. Create child scopes in Unique for each space (using the space key as scope name)
7. Fetch and ingest new or updated pages (HTML storage representation)
8. Download and ingest new or updated attachments (streamed)
9. Delete items from Unique that are no longer discovered

### How does change detection work?

**Answer:** The connector uses a server-side file diff mechanism that compares discovered items per space against the state stored in Unique, returning which items are new, updated, deleted, or moved. Only new and updated items are fetched and ingested. See the [file diff mechanism](./technical/flows.md#file-diff-mechanism) documentation for the full details including item attributes, partial key format, and diagrams.

### What happens when a label is removed from a page?

**Answer:** If the `ai-ingest` label is removed from a page (and the page is not also covered by an ancestor's `ai-ingest-all` label), the page is no longer discovered during the scan. The file diff detects the page as missing and it is deleted from the Unique knowledge base on the next sync cycle. The same applies to any attachments on that page.

If the `ai-ingest-all` label is removed from a parent page, all descendant pages that were previously discovered solely through that label are no longer found. They are deleted from Unique on the next sync cycle, unless they carry their own `ai-ingest` label or are descendants of another `ai-ingest-all`-labeled page.

### What happens when a page is deleted from Confluence?

**Answer:** If the page's space is still discovered during the next sync cycle, the file diff detects the missing page and deletes the corresponding content (page and its attachments) from Unique.

If an entire previously synced space disappears from discovery results (for example, because all its labels were removed or the space was deleted), the connector does not automatically clean up its content. This is because the file diff runs per-space and only executes for spaces that still appear in the current discovery results. Content from the disappeared space remains in Unique and requires manual deletion.

### What happens to attachments when their parent page is unlabeled?

**Answer:** Attachments are discovered as children of labeled pages. If a page is no longer discovered (because its label was removed or the page was deleted), its attachments are also missing from the discovery results and are deleted from Unique via the file diff mechanism.

### How are scopes organized in Unique?

**Answer:** Scopes follow a two-level hierarchy: a root scope configured per tenant, and child scopes automatically created for each Confluence space key. Child scopes inherit access from the root scope. See the [Scope Hierarchy](./technical/flows.md#scope-hierarchy) for details.

### What is the ingestion key format?

**Answer:** The key format determines how content is identified in Unique:

| Format | Key Pattern (pages) | Key Pattern (attachments) |
|---|---|---|
| Default (v2) | `<tenantName>/<spaceId>_<spaceKey>/<pageId>` | `<tenantName>/<spaceId>_<spaceKey>/<pageId>::<attachmentId>` |
| v1 compatible | `<spaceId>_<spaceKey>/<pageId>` | `<spaceId>_<spaceKey>/<pageId>::<attachmentId>` |

The v1 format can be enabled via `ingestion.useV1KeyFormat: enabled` for backward compatibility during migration from v1.

## Safety and Deletion

### What safety guards does the connector have?

**Answer:** The connector includes two safeguards -- a zero-submission guard and a full-deletion guard -- that abort the current tenant sync cycle when the file diff results indicate a likely error in discovery or key format for a space. To intentionally remove all content from a space, leave at least one page labeled for synchronization to avoid triggering these guards. See the [safety checks](./technical/flows.md#safety-checks) documentation for full details.

### Are concurrent syncs for the same tenant possible?

**Answer:** No. If a sync cycle is already running for a tenant when the next scheduled cycle triggers, the new cycle is skipped.

## Troubleshooting

### Why aren't my pages syncing?

**Checklist:**

1. Does the page have the `ai-ingest` or `ai-ingest-all` label? (Check that the label names match your tenant configuration.)
2. Is the page in a global space? (Cloud: also includes collaboration spaces.)
3. Is the page a standard page type? (Databases, whiteboards, and embeds are skipped.)
4. Does the page have a non-empty body? Pages with empty bodies are discovered but skipped during content ingestion.
5. Is the tenant status set to `active` in the YAML config?
6. Check connector logs for errors related to authentication, API rate limits, or Unique API failures.

### Why aren't attachments being ingested?

**Checklist:**

1. Is attachment ingestion enabled? (`ingestion.attachments.mode` must be `enabled`, which is the default.)
2. Does the file extension appear in the `allowedExtensions` list?
3. Is the file smaller than the configured `maxFileSizeMb` (default: 200 MB)?
4. Is the file size greater than 0 bytes? (Zero-byte attachments are skipped.)
5. Check connector logs for attachment-specific errors.

### Why do I see "Aborting to prevent accidental full deletion" errors?

**Answer:** This means the safety guard was triggered. Possible causes:

- A bug in page discovery returned zero results for a space (e.g., Confluence API issue, authentication failure for specific spaces)
- The ingestion key format changed (e.g., `useV1KeyFormat` was toggled), causing the diff to see all existing keys as unrecognized

**Resolution:**

1. Check Confluence API connectivity and authentication
2. Verify that the `useV1KeyFormat` setting has not changed unexpectedly
3. If the key format change was intentional, the old content must be cleaned up manually before switching formats

### Why is sync taking too long?

**Possible causes:**

- Large number of labeled pages and descendants
- Large attachments being downloaded and uploaded
- Low API rate limit configuration
- Low processing concurrency

**Solutions:**

1. Increase `processing.concurrency` (default: 1)
2. Increase `confluence.apiRateLimitPerMinute` if the Confluence instance allows higher throughput
3. Increase `unique.apiRateLimitPerMinute` if the Unique platform allows higher throughput
4. Review labeled pages and reduce scope if necessary
5. Adjust `processing.scanIntervalCron` to allow more time between cycles

### How does the connector handle errors during ingestion?

**Answer:** Individual item failures are logged and skipped without aborting the entire sync cycle. At the end of each batch, a summary is logged showing how many items succeeded and how many failed.

## Multi-Tenancy

### Can one connector serve multiple Confluence instances?

**Answer:** Yes. Each Confluence instance is configured as a separate tenant with its own YAML configuration file. All tenants run within a single connector deployment with independent authentication, API clients, and sync schedules. See [Architecture -- Multi-Tenancy Model](./technical/architecture.md#multi-tenancy-model) for details on tenant isolation and per-tenant service instances.

### How do I add a new tenant?

**Answer:** Create a new YAML configuration file following the naming convention `<tenant-name>-tenant-config.yaml` in the directory matched by the `TENANT_CONFIG_PATH_PATTERN` environment variable. The connector must be restarted to pick up new tenant configuration files.

### Can two tenants use the same scope ID?

**Answer:** This is not recommended. Each tenant should have its own root scope to avoid conflicts in scope ownership and content management.

## Performance

### What are the API rate limits?

**Answer:** Both Confluence and Unique API rate limits are independently configurable per tenant:

| API | Configuration Key | Default |
|---|---|---|
| Confluence | `confluence.apiRateLimitPerMinute` | No default (must be set) |
| Unique | `unique.apiRateLimitPerMinute` | 100 requests/minute |

Rate limiting is enforced client-side.

### What is the initial sync behavior?

**Answer:** An initial sync is triggered immediately on startup for each active tenant. After that, syncs follow the configured cron schedule.

## Permissions

### What Confluence permissions does the connector need?

**Answer:** The connector requires read access to the Confluence instance. OAuth 2.0 (2LO) and PAT credentials grant instance-wide read access — there is no way to scope them down to specific spaces or pages.

- **OAuth 2.0 (2LO):** The OAuth application is configured with read access to the entire Confluence instance.
- **Personal Access Token (Data Center below 10.1 only; not recommended):** The PAT inherits the permissions of the user who created it. Use OAuth 2.0 (2LO) on Data Center 10.1+ instead.

The connector discovers pages via CQL search queries filtered by label. Only pages carrying the configured sync labels are ingested.

### What happens if the connector lacks permission to a space?

**Answer:** Pages in inaccessible spaces are silently excluded from CQL search results. The connector does not receive an error; it simply never discovers those pages.

If a space that was previously accessible becomes inaccessible, the connector does not automatically clean up that space's already ingested content. The file diff runs per-space and only executes for spaces that still appear in discovery results, so a space that vanishes from CQL results is never diffed and its content remains in Unique. Manual cleanup is required in that situation.

### How does Unique platform authentication work?

**Answer:** The connector supports two modes: `cluster_local` for in-cluster deployments (using service headers) and `external` for out-of-cluster deployments (using Zitadel OAuth credentials). See the [Authentication Guide](./operator/authentication.md) for setup details, required YAML fields, and token flows.

## Resource Requirements

### What are the resource requirements?

**Answer:** The default Helm chart values specify the following Kubernetes resource settings:

| Resource | Value |
|---|---|
| CPU request | 1 core |
| CPU limit | Not set |
| Memory request | 512 Mi |
| Memory limit | 1 Gi |
| Node.js max heap (`MAX_HEAP_MB`) | 1920 MB |

These defaults are suitable for a single-tenant deployment with moderate page counts. For deployments with many tenants, large numbers of labeled pages, or high concurrency settings, consider increasing memory limits accordingly.

## Related Documentation

- [README](./README.md) - Overview, features, and quick summary
- [Operator Guide](./operator/README.md) - Deployment and operations
- [Authentication](./operator/authentication.md) - Confluence and Unique auth setup
- [Configuration](./operator/configuration.md) - Tenant config, environment variables, YAML settings
- [Technical Reference](./technical/README.md) - Architecture, flows, and design decisions

## Standard References

- [Confluence Cloud REST API](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Confluence Query Language (CQL)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/) - CQL reference for content search queries
