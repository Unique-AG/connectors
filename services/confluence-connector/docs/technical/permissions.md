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

| API Endpoint | Method | Use Case                                                                                           |
|---|---|----------------------------------------------------------------------------------------------------|
| `/wiki/rest/api/content/search?cql=...` | GET | Search for labeled pages using CQL; discover descendant pages via `ancestor IN (...)`              |
| `/wiki/rest/api/content/search?cql=id%3D{pageId}` | GET | Fetch a single page with `body.storage` for content ingestion                                      |
| `/wiki/api/v2/pages/{pageId}/attachments` | GET | Fetch attachment list for pages exceeding the Confluence-imposed inline limit (max 25 attachments) |
| `/wiki/rest/api/content/{pageId}/child/attachment/{attachmentId}/download` | GET | Download attachment binary content                                                                 |

### Space Type Filter

The Cloud client filters by `space.type=global OR space.type=collaboration`. See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on space type filtering. The OAuth integration must have access to spaces of both types to discover all labeled pages.

## Confluence Data Center Permissions

### Required API Access

The Data Center API client calls the following endpoints directly against the Confluence instance (`<baseUrl>`):

| API Endpoint | Method | Use Case                                                                                          |
|---|---|---------------------------------------------------------------------------------------------------|
| `/rest/api/content/search?cql=...` | GET | Search for labeled pages using CQL; discover descendant pages via `ancestor IN (...)`             |
| `/rest/api/content/{pageId}` | GET | Fetch a single page with `body.storage` for content ingestion                                     |
| `/rest/api/content/{pageId}/child/attachment` | GET | Paginate through attachment lists exceeding the Confluence-imposed inline limit (max 25 per page) |

Attachment binary content is downloaded from the path provided in each attachment's `_links.download` metadata field.

### Space Type Filter

The Data Center client filters by `space.type=global` only (`collaboration` is a Cloud-only space type). See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on space type filtering. The service account has instance-wide read access; space type filtering is applied client-side via CQL.

## Permission Justification

### Confluence (Cloud and Data Center)

The connector only reads content from Confluence — it never creates, updates, or deletes pages or attachments. On Data Center, the OAuth 2.0 token request explicitly includes `scope=READ` to enforce least privilege at the token level.

### Unique Platform

The connector requires scope management and ingestion access because it:

- Creates child scopes for each Confluence space
- Registers, uploads, and finalizes content during ingestion
- Queries and removes previously ingested content during deletion

See the [Authentication Guide](../operator/authentication.md) for setup instructions.

## Related Documentation

- [Authentication](../operator/authentication.md) - Confluence and Unique authentication setup
- [Architecture](./architecture.md) - System components and infrastructure
- [Flows](./flows.md) - Content sync and file diff flow details

## Standard References

- [Confluence Cloud REST API v1](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Cloud REST API v2](https://developer.atlassian.com/cloud/confluence/rest/v2/intro/) - Atlassian Confluence Cloud v2 API documentation
- [Confluence Data Center REST API](https://developer.atlassian.com/server/confluence/rest/) - Atlassian Confluence Data Center API documentation
