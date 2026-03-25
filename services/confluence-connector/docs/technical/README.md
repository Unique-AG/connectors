<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

# Technical Reference

The Confluence Connector v2 (`@unique-ag/confluence-connector`) is a Node.js service built on NestJS that synchronizes page content and file attachments from Confluence to the Unique platform for RAG ingestion. It supports both Confluence Cloud and Confluence Data Center deployments.

**Core Capabilities:**

- Discovers pages via Confluence Query Language (CQL) label searches
- Fetches page content in HTML (Confluence storage representation) and downloads file attachments
- Computes per-space file diffs against previously ingested state to detect new, updated, and deleted items
- Ingests content into the Unique knowledge base via the Unique API (register, upload, finalize)
- Manages scope hierarchies automatically (root scope plus one child scope per Confluence space)
- Operates on a configurable cron schedule (default: every 15 minutes)

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System components, module structure, multi-tenancy model |
| [Flows](./flows.md) | Content sync, file diff mechanism, discovery, ingestion |
| [Permissions](./permissions.md) | Confluence API and Unique platform permissions |
| [Security](./security.md) | Security practices, authentication strategies, SBOM |

## Key Concepts

### Pull-Based Architecture

The Confluence Connector v2 **pulls** content from Confluence on a scheduled basis:

```mermaid
flowchart LR
    subgraph PullV2["Confluence Connector v2: Pull-Based"]
        Connector["Confluence Connector"] -->|"Pulls pages & attachments"| Confluence["Confluence"]
        Connector -->|"Pushes content"| Unique["Unique Platform"]
    end
```

- The connector queries the Confluence REST API for labeled pages using CQL
- Content is fetched, diffed, and ingested into Unique
- Scheduling is controlled via a per-tenant cron expression (default: `*/15 * * * *`)

### Label-Driven Page Discovery

Pages are not automatically synced. Users must apply Confluence labels to mark pages for synchronization:

```mermaid
flowchart LR
    User["Confluence User"] -->|"Applies label"| Label["ingestSingleLabel / ingestAllLabel (configurable)"]
    Label --> Scanner["Page Scanner (CQL)"]
    Scanner -->|"Discovers pages"| Diff["File Diff"]
    Diff -->|"New/Updated"| Ingest["Ingest into Unique"]
    Diff -->|"Deleted"| Delete["Remove from Unique"]
```

Two labels control discovery:

| Label | Behavior |
|-------|----------|
| `ingestSingleLabel` (recommended: `ai-ingest`) | Marks an individual page for synchronization |
| `ingestAllLabel` (recommended: `ai-ingest-all`) | Marks a page and all its descendant pages for synchronization |

Labels are REQUIRED fields in the tenant configuration. There is no schema default; operators must explicitly set `ingestSingleLabel` and `ingestAllLabel` in each tenant's YAML.

The scanner filters by space type: Cloud searches `global` and `collaboration` spaces, Data Center searches `global` spaces only. Content types `database`, `whiteboard`, and `embed` are discovered but skipped.

### File Diff Mechanism

The connector computes diffs per Confluence space by comparing discovered items against the state stored in Unique:

- **New items**: Discovered pages/attachments not previously ingested
- **Updated items**: Items with a changed `updatedAt` timestamp
- **Deleted items**: Previously ingested items no longer discovered (label removed or page deleted)

Two safety checks prevent accidental full deletion:
1. If zero items are submitted to the diff but deletions are returned, the sync aborts
2. If the diff would delete all files stored in Unique for a given space, the sync aborts

See [Flows](./flows.md) for the detailed file diff sequence.

### Scope Management

Each tenant has a root scope that must pre-exist in the Unique platform. The connector grants itself access to the configured root scope and then verifies it exists at the start of every sync cycle. Child scopes are created automatically for each Confluence space, using the space key as the scope name. Scopes are created with `inheritAccess: true`, so they inherit access from the root scope.

Scope external IDs follow the format: `confc:<tenantName>:<spaceKey>`.

### Multi-Tenancy

Multiple Confluence instances (tenants) can be configured in a single deployment. Each tenant is isolated via `AsyncLocalStorage` and has its own:

- Confluence API client (Cloud or Data Center)
- Authentication strategy (OAuth 2.0 2LO or PAT)
- Unique API client
- Sync schedule and concurrency settings
- Service instances (scanner, content fetcher, file diff, ingestion, scope management)

Tenant configuration files are loaded from YAML files matching the glob pattern set in `TENANT_CONFIG_PATH_PATTERN` (e.g., `/app/tenant-configs/*-tenant-config.yaml`). See the [Operator Guide](../operator/README.md) for configuration details. The filename determines the tenant name (e.g., `my-tenant-tenant-config.yaml` yields tenant name `my-tenant`). Tenant names must match the pattern `^[a-z0-9]+(-[a-z0-9]+)*$`.

Each tenant has a status (`active`, `inactive`, or `deleted`). Only `active` tenants are registered and scheduled.

### Authentication

**Confluence authentication:**

| Instance Type | Auth Method | Description |
|---|---|---|
| Cloud | OAuth 2.0 (2LO) | Client credentials flow via Atlassian API |
| Data Center | OAuth 2.0 (2LO) | Client credentials flow via the instance's token endpoint |
| Data Center | Personal Access Token | Static token-based authentication |

**Unique platform authentication** (configured via `serviceAuthMode`):

| Auth Mode | Description |
|---|---|
| `cluster_local` | For connectors in the same Kubernetes cluster as Unique. Uses service headers (`x-company-id`, `x-user-id`). Upload URLs are rewritten to the ingestion service's scoped upload endpoint to avoid hairpinning through the gateway. |
| `external` | For connectors outside the cluster. Uses Zitadel OAuth credentials (`zitadelOauthTokenUrl`, `zitadelClientId`, `zitadelClientSecret`, `zitadelProjectId`). |

### API Clients

The connector uses two concrete implementations of the abstract `ConfluenceApiClient`:

| Client | Instance Type | API Base | Space Type Filter |
|---|---|---|---|
| `CloudConfluenceApiClient` | Cloud | `https://api.atlassian.com/ex/confluence/<cloudId>` | `global`, `collaboration` |
| `DataCenterConfluenceApiClient` | Data Center | `<baseUrl>` (direct) | `global` |

Both clients use CQL to search for labeled pages and fetch descendants. Key differences:

- **Attachment pagination**: Cloud uses the v2 REST API (`/wiki/api/v2/pages/<id>/attachments`) for pages with more than 25 attachments (v1 pagination returns 410 Gone). Data Center follows v1 `_links.next` pagination links.
- **Attachment download**: Cloud uses `/wiki/rest/api/content/<pageId>/child/attachment/<attachmentId>/download` through the Atlassian API gateway. Data Center uses `_links.download` directly.
- **Page URLs**: Cloud builds URLs from `_links.webui`. Data Center uses `/pages/viewpage.action?pageId=<id>`.

### Ingestion Pipeline

Content flows through a 3-step pipeline for each item (page or attachment):

1. **Register**: `registerContent` sends metadata including key, title, mimeType, scopeId, sourceKind, and other metadata to the Unique ingestion API
2. **Upload**: The content is uploaded via HTTP PUT to the returned `writeUrl` (page HTML as a buffer, attachments as a stream)
3. **Finalize**: `finalizeIngestion` triggers downstream processing in Unique

Pages are ingested as `text/html`. Attachments use their original media type. Both use `sourceKind` values:
- Cloud: `ATLASSIAN_CONFLUENCE_CLOUD`
- Data Center: `ATLASSIAN_CONFLUENCE_ONPREM`

Ingestion concurrency is controlled by the `processing.concurrency` setting (default: 1). Progress is logged every 100 items.

### v1-Compatible Key Format

By default, ingestion keys include a tenant name prefix: `<tenantName>/<spaceId>_<spaceKey>/<pageId>`. When `useV1KeyFormat` is enabled, the tenant prefix is omitted: `<spaceId>_<spaceKey>/<pageId>`. This is for backward compatibility with content previously ingested by Confluence Connector v1.

## Related Documentation

- [Operator Guide](../operator/README.md) - Deployment, configuration, and operations
- [FAQ](../faq.md) - Frequently asked questions
- [Confluence Connector Overview](../README.md) - End-user documentation

## Standard References

- [Confluence Cloud REST API](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Atlassian Cloud Authentication](https://developer.atlassian.com/cloud/confluence/security-for-connect-apps/) - Atlassian authentication documentation
- [Confluence Query Language (CQL)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/) - CQL reference for content search queries
