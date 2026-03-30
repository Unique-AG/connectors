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

### Required API Access

The Cloud API client calls the following endpoints through the Atlassian API gateway (`https://api.atlassian.com/ex/confluence/<cloudId>`):

| API Endpoint | Method | Use Case |
|---|---|---|
| `/wiki/rest/api/content/search?cql=...` | GET | Search for labeled pages using CQL; discover descendant pages via `ancestor IN (...)` |
| `/wiki/rest/api/content/search?cql=id%3D{pageId}` | GET | Fetch a single page with `body.storage` for content ingestion |
| `/wiki/api/v2/pages/{pageId}/attachments` | GET | Fetch attachment list for pages exceeding the Confluence-imposed inline limit (typically 25 attachments; v1 pagination returns 410 Gone) |
| `/wiki/rest/api/content/{pageId}/child/attachment/{attachmentId}/download` | GET | Download attachment binary content |

All endpoints use the `GET` method and require read access only.

### Space Type Filter

The Cloud client filters by `space.type=global OR space.type=collaboration`. See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on space type filtering. The OAuth integration must have access to spaces of both types to discover all labeled pages.

## Confluence Data Center Permissions

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

## Permission Justification

### Confluence Cloud: Read-Only Access

**Justification:** The connector only reads content from Confluence. It never creates, updates, or deletes pages or attachments. All Confluence API calls use the `GET` method.

**Why read-only is sufficient:**

- CQL search is a read operation
- Page content fetch is a read operation
- Attachment listing and download are read operations
- No write operations are performed against Confluence

### Confluence Data Center: Explicit READ Scope

**Justification:** The Data Center OAuth 2.0 token request explicitly includes `scope=READ`, limiting the service account to read-only operations even if the application link grants broader permissions.

**Why not broader scopes?**

- The connector only reads content -- no write access is needed
- Explicit `READ` scope enforces least privilege at the token level
- Reduces risk if the application link is misconfigured with broader permissions

### Unique Platform: Scope Management and Ingestion

**Justification:** The connector creates scopes and ingests content into the Unique platform. The service user requires sufficient privileges to manage scopes and perform content ingestion.

**Why needed?**

- The connector creates child scopes for each Confluence space
- Content ingestion requires registering, uploading, and finalizing content
- File deletion requires querying and removing previously ingested content

See the [Authentication Guide](../operator/authentication.md) for setup instructions.

## Related Documentation

- [Authentication](../operator/authentication.md) - Confluence and Unique authentication setup
- [Architecture](./architecture.md) - System components and infrastructure
- [Flows](./flows.md) - Content sync and file diff flow details

## Standard References

- [Confluence Cloud REST API v1](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Cloud REST API v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/) - Atlassian Confluence Cloud v2 API documentation
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Atlassian OAuth 2.0 (3LO) apps](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/) - Atlassian Cloud OAuth app setup (prerequisite for 2LO client credentials)
- [Confluence Data Center - Configure an incoming link](https://confluence.atlassian.com/doc/configure-an-incoming-link-1115674733.html) - Data Center OAuth 2.0 application link setup
