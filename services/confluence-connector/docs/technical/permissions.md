<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The Confluence Connector requires specific permissions to access the Confluence REST API and the Unique platform API. This document lists all required permissions, maps them to the API endpoints the connector calls, and explains why each is needed.

## Permission Summary

### Confluence API Permissions

| Instance Type | Auth Method | Permissions Required |
|---|---|---|
| Cloud | OAuth 2.0 (2LO) | OAuth application configured for the client credentials flow with instance-wide read access (no explicit OAuth scopes are sent in the token request) |
| Data Center | OAuth 2.0 (2LO) | OAuth 2.0 application configured with `READ` scope (instance-wide) |
| Data Center (below 10.1) | Personal Access Token (not recommended) | Inherits the permissions of the user who created it. Use OAuth 2.0 (2LO) on Data Center 10.1+ instead. |

### Unique Platform Permissions

| Auth Mode | Permissions Required |
|---|---|
| `cluster_local` | Service identity headers (`x-company-id`, `x-user-id`) for a user with scope management and ingestion access |
| `external` | Zitadel service account with scope management and ingestion access |

## Confluence Cloud Permissions

### Authentication Model

Confluence Cloud uses OAuth 2.0 two-legged (client credentials) authentication via the centralized Atlassian identity endpoint (`https://api.atlassian.com/oauth/token`). The token request sends `grant_type`, `client_id`, and `client_secret` as a JSON body. No explicit OAuth scopes are included in the token request; the access token inherits the permissions of the service account configured in the Atlassian Admin Console.

### Required API Access

The Cloud API client calls the following endpoints through the Atlassian API gateway (`https://api.atlassian.com/ex/confluence/<cloudId>`):

| API Endpoint | Method | Use Case |
|---|---|---|
| `/wiki/rest/api/content/search?cql=...` | GET | Search for labeled pages using CQL; discover descendant pages via `ancestor IN (...)` |
| `/wiki/rest/api/content/search?cql=id%3D{pageId}` | GET | Fetch a single page with `body.storage` for content ingestion |
| `/wiki/api/v2/pages/{pageId}/attachments` | GET | Fetch attachment list for pages exceeding the Confluence-imposed inline limit (typically 25 attachments; v1 pagination returns 410 Gone) |
| `/wiki/rest/api/content/{pageId}/child/attachment/{attachmentId}/download` | GET | Download attachment binary content |

All endpoints use the `GET` method and require read access only.

### CQL Query Expand Parameters

The connector requests the following expand fields on search queries:

| Expand Field | Purpose |
|---|---|
| `metadata.labels` | Read page labels to determine sync eligibility |
| `version` | Read version timestamps for file diff comparison |
| `space` | Read space key, ID, and name for scope management |
| `children.attachment` | Inline attachments per page up to the Confluence-imposed limit (typically 25; when attachments are enabled) |
| `children.attachment.version` | Read attachment version timestamps (when attachments are enabled) |
| `children.attachment.extensions` | Read attachment media type and file size (when attachments are enabled) |
| `body.storage` | Read page HTML content for ingestion (single page fetch only) |

### Space Type Filter

The Cloud client filters by `space.type=global OR space.type=collaboration`. See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on space type filtering. The OAuth integration must have access to spaces of both types to discover all labeled pages.

## Confluence Data Center Permissions

### Authentication Models

Data Center supports two authentication methods:

**OAuth 2.0 (2LO):** Client credentials flow against the instance's own token endpoint (`<baseUrl>/rest/oauth2/latest/token`). The token request sends `grant_type`, `client_id`, `client_secret`, and `scope=READ` as a URL-encoded form body. The `READ` scope explicitly limits the service account to read-only access.

**Personal Access Token (PAT) -- not recommended, Data Center below 10.1 only:** A static bearer token associated with a Data Center user account. The token inherits the permissions of the user who created it. The PAT inherits the user's instance-level permissions. PATs do not expire automatically and must be manually rotated. Use OAuth 2.0 (2LO) on Data Center 10.1+ instead.

### Required API Access

The Data Center API client calls the following endpoints directly against the Confluence instance (`<baseUrl>`):

| API Endpoint | Method | Use Case |
|---|---|---|
| `/rest/api/content/search?cql=...` | GET | Search for labeled pages using CQL; discover descendant pages via `ancestor IN (...)` |
| `/rest/api/content/{pageId}` | GET | Fetch a single page with `body.storage` for content ingestion |
| `{_links.download}` | GET | Download attachment binary content (path from attachment metadata) |
| `{_links.next}` | GET | Paginate through attachment lists exceeding the Confluence-imposed inline limit (typically 25 per page) |

All endpoints use the `GET` method and require read access only.

### Space Type Filter

The Data Center client filters by `space.type=global` only (`collaboration` is a Cloud-only space type). See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on space type filtering. The service account has instance-wide read access; space type filtering is applied client-side via CQL.

## Unique Platform Permissions

The connector performs the following operations against the Unique platform API, grouped by service domain.

### User Operations

| API Operation | Purpose |
|---|---|
| `users.getCurrentId()` | Retrieve the service user's own ID for self-granting scope access |

### Scope Operations

| API Operation | Purpose |
|---|---|
| `scopes.createAccesses(scopeId, accesses)` | Grant `MANAGE`, `READ`, and `WRITE` access to the service user on the root scope; grant `READ` access on parent scopes in the hierarchy |
| `scopes.getById(scopeId)` | Read the root scope and traverse parent scopes to build the scope path |
| `scopes.createFromPaths(paths, options)` | Create child scopes for each Confluence space (one scope per space key, with `inheritAccess: true`) |
| `scopes.updateExternalId(scopeId, externalId)` | Set the external ID on newly created space scopes (format: `confc:<tenantName>:<spaceKey>`) |

### Ingestion Operations

| API Operation | Purpose |
|---|---|
| `ingestion.registerContent(request)` | Register a page or attachment for ingestion (returns `writeUrl` and `readUrl`) |
| `ingestion.finalizeIngestion(request)` | Finalize ingestion after content upload |
| `ingestion.performFileDiff(items, partialKey, sourceKind, baseUrl)` | Compute per-space file diff to detect new, updated, and deleted items |

### File Operations

| API Operation | Purpose |
|---|---|
| `files.getByKeys(contentKeys)` | Resolve content keys to file IDs for deletion |
| `files.deleteByIds(contentIds)` | Delete files that are no longer discovered (label removed or page deleted) |
| `files.getCountByKeyPrefix(partialKey)` | Count total files for a space key prefix to validate against accidental full deletion |

### Required Service User Capabilities

The Unique service user (whether authenticated via `cluster_local` headers or `external` Zitadel credentials) must have sufficient privileges to:

1. Read its own user ID
2. Create and manage scope access entries (MANAGE, READ, WRITE)
3. Read scope details and traverse scope hierarchies
4. Create scopes from paths and update their external IDs
5. Register content, upload files, and finalize ingestion
6. Query and delete files by key

See the [Authentication Guide](../operator/authentication.md) for setup instructions.

## Permission Justification

### Confluence: Read-Only Access

**Justification:** The connector only reads content from Confluence. It never creates, updates, or deletes pages or attachments. All Confluence API calls use the `GET` method.

**Why read-only is sufficient:**
- CQL search is a read operation
- Page content fetch (`body.storage`) is a read operation
- Attachment listing and download are read operations
- No write operations are performed against Confluence

### Data Center: Explicit READ Scope

**Justification:** The Data Center OAuth 2.0 token request explicitly includes `scope=READ`, limiting the service account to read-only operations even if the application link grants broader permissions.

### Unique: Self-Granting Scope Access

**Justification:** The connector grants itself `MANAGE`, `READ`, and `WRITE` access on the root scope at the start of each sync cycle. This is necessary because the service user needs to manage child scopes (create, set external IDs) and ingest content into those scopes.

**Why MANAGE access?**
- Creating child scopes under the root scope requires management permission
- Updating external IDs on scopes requires management permission

**Why WRITE access?**
- Registering and finalizing content ingestion requires write permission on the target scope

**Why READ access on parent scopes?**
- The connector traverses the scope hierarchy upward from the root scope to build the full scope path, which requires read access on each ancestor scope

## Rate Limits

### Confluence API Rate Limiting

The connector enforces client-side rate limiting via the `apiRateLimitPerMinute` configuration parameter, implemented using a Bottleneck token-bucket limiter. The reservoir refills every 60 seconds.

| Configuration | Description | Location |
|---|---|---|
| `confluence.apiRateLimitPerMinute` | Maximum Confluence API requests per minute (required, no default) | Tenant config YAML |

Atlassian Cloud enforces its own server-side rate limits. When the connector exceeds the server limit, the HTTP client's built-in retry interceptor handles retries.

Data Center rate limits depend on the instance's configuration and available resources. Operators should set `apiRateLimitPerMinute` according to their instance's capacity.

### Unique API Rate Limiting

The connector also rate-limits requests to the Unique platform API:

| Configuration | Default | Description |
|---|---|---|
| `unique.apiRateLimitPerMinute` | 100 | Maximum Unique API requests per minute |

## Related Documentation

- [Authentication](../operator/authentication.md) - Confluence and Unique authentication setup
- [Architecture](./architecture.md) - System components and module structure
- [Flows](./flows.md) - Content sync and file diff flow details

## Standard References

- [Confluence Cloud REST API v1](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Cloud REST API v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/) - Atlassian Confluence Cloud v2 API documentation
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Atlassian OAuth 2.0 (3LO) apps](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/) - Atlassian Cloud OAuth app setup (prerequisite for 2LO client credentials)
- [Confluence Data Center - Configure an incoming link](https://confluence.atlassian.com/doc/configure-an-incoming-link-1115674733.html) - Data Center OAuth 2.0 application link setup
