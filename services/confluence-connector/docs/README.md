<!-- confluence-page-id: 1504182474 -->
<!-- confluence-space-key: PUBDOC -->

## Overview

The Confluence Connector is a service that synchronizes page content and file attachments from Confluence to the Unique knowledge base for RAG ingestion. It supports both Confluence Cloud and Confluence Data Center deployments.

For deployment, configuration, and operational details, see the [IT Operator Guide](./operator/README.md).

## Quick Summary

**What it does:** Synchronizes labeled Confluence pages and their attachments to Unique's AI knowledge base

**Supported platforms:** Confluence Cloud and Confluence Data Center

**Authentication:** OAuth 2.0 two-legged (recommended; Cloud and Data Center 10.1+) or Personal Access Token (Data Center below 10.1 only; not recommended)

**Scheduling:** Configurable automated scans (default: every 15 minutes)

**Multi-tenancy:** Multiple Confluence instances can be managed in a single deployment

**Deployment:** Kubernetes-based containerized application

## Requirements

### Confluence

| Requirement | Details |
|---|---|
| **Confluence Cloud** | Active instance with an Atlassian Cloud ID |
| **Confluence Data Center** | Self-hosted instance with REST API access |
| **Authentication** | OAuth 2.0 application credentials (recommended) or a Personal Access Token (Data Center below 10.1 only; not recommended) |
| **Permissions** | Read access to spaces and pages that should be synchronized |

**Prerequisites:**

- Ability to create and apply labels on Confluence pages
- An OAuth 2.0 application configured in Confluence (recommended), or a PAT for Data Center below 10.1 only (not recommended)
- A configured scope in the Unique platform to receive ingested content

### Authentication Methods

The connector supports OAuth 2.0 two-legged (2LO) for both Confluence Cloud and Data Center (10.1+), which is the recommended authentication method. Personal Access Token (PAT) is supported only on Data Center versions below 10.1 where OAuth 2.0 (2LO) is not available, and is not recommended. For Unique platform communication, `cluster_local` mode is available for in-cluster deployments and `external` mode for out-of-cluster deployments via Zitadel OAuth. See the [Authentication Guide](./operator/authentication.md) for full setup instructions, credential management, and token flows.

## Features

### Core Capabilities

**Label-Driven Page Discovery**

- Pages are discovered via configurable Confluence labels and ingested in HTML format (Confluence storage representation)
- A configurable label (e.g. `ai-ingest`) marks individual pages for synchronization
- A second configurable label (e.g. `ai-ingest-all`) marks a page and all its descendant pages for synchronization
- Operators must explicitly set both label names in their tenant configuration
- Only pages in global spaces are scanned (Cloud also includes collaboration spaces)

**Automatic Change Detection**

- A per-space [file diff mechanism](./technical/flows.md#File-Diff-Mechanism) compares discovered items against the state stored in Unique, ingesting only new or modified items and removing deleted ones
- [Safety checks](./technical/flows.md#Safety-Checks) prevent accidental full deletion of content

**Attachment Ingestion**

- File attachments on labeled pages are discovered and ingested alongside page content
- Attachment ingestion can be enabled or disabled
- Configurable file size limit (default: 200 MB)
- Configurable allowed MIME types. Defaults cover PDF, the major Office formats, plain text, CSV, HTML, PNG, and JPEG. See [Configuration](./operator/configuration.md#Attachment-Configuration) for the full list.

**Image Ingestion**

When attachment ingestion is enabled, images embedded in a Confluence page (PNG and JPEG) are inlined as base64 data URIs inside the page HTML. The connector parses each page's Confluence storage XML and replaces every `<ac:image>` macro that points to a Confluence attachment with an `<img src="data:image/...;base64,...">` element. The result is a single self-contained page artifact per Confluence page.

Both attachments of the page itself and attachments from another page in the same instance (referenced via `<ri:attachment><ri:page/></ri:attachment>`) are resolved through the existing Confluence client. External image references (`<ac:image><ri:url ri:value="https://..."/></ac:image>`) are left untouched in the HTML and never fetched.

When inlining is enabled, image attachments are not ingested as standalone artifacts. Orphan images (attached to the page but not referenced by an in-body macro) are appended to the end of the page body so their content is still inlined. A macro-referenced image that cannot be inlined (download failure, larger than `attachments.maxFileSizeMb`, a MIME type not in `allowedMimeTypes`, or a cross-page reference whose page or filename cannot be resolved) keeps its original macro and is not ingested elsewhere.

`attachments.imageOcr` (enabled by default) only applies when inlining is off and images go through the standalone path. Set it to `disabled` to defer to the destination scope's own `ingestionConfig.jpgReadMode`. Other image formats (GIF, WebP, SVG, HEIC, BMP, TIFF) are not currently supported by the Unique ingestion service and should be left out of `allowedMimeTypes`.

**Skipped Content Types**

Content types `database`, `whiteboard`, and `embed` are explicitly skipped (no body available via API). Folders are not explicitly skipped but have no body, so they are excluded during ingestion. In both cases, descendants (such as sub-pages under a database or folder) are still discovered and ingested. Live Docs pass through as regular pages. See the [Content Type Ingestion Map](./technical/flows.md#Content-Type-Ingestion-Map) for the full breakdown by platform.

**Scope Management**

- A pre-existing root scope is configured per tenant (must be created in Unique before the connector starts), with child scopes automatically created per Confluence space
- See the [Scope Hierarchy](./technical/flows.md#Scope-Hierarchy) for details

**Scheduled Synchronization**

- Sync runs on a configurable cron schedule (default: `*/15 * * * *`, every 15 minutes)
- An initial sync is triggered immediately on startup for each tenant
- Concurrent sync runs for the same tenant are prevented (the second run is skipped)

### Advanced Features

**Multi-Tenancy**

- Multiple Confluence instances (tenants) can be configured in a single deployment, each with independent configuration, authentication, and sync schedules. See [Architecture -- Multi-Tenancy Support](./technical/architecture.md#Multi-Tenancy-Support) for the isolation model and per-tenant service details.

**Concurrency Control**

- Configurable page ingestion concurrency (default: 1)
- Configurable API rate limits for both Confluence and Unique APIs

**Observability**

- Structured JSON logging
- OpenTelemetry metrics integration
- Prometheus metrics endpoint

**Security**

- OAuth 2.0 two-legged (2LO) authentication for Cloud and Data Center
- Personal Access Token (PAT) support for Data Center below 10.1 only (not recommended; use OAuth 2.0 2LO on 10.1+)
- Configurable rate limiting for Confluence and Unique API calls

**v1-Compatible Key Format**

- Optional `useV1KeyFormat` setting for backward compatibility with Confluence Connector v1 ingestion keys

## How It Works

### High-Level Sync Flow

```mermaid
flowchart TB
  Start(("Scheduler"))

  subgraph TenantSync["For Each Tenant"]
    direction TB

    InitScope["Initialize Root Scope"]
    Discover["Discover Labeled Pages & Attachments"]
    Diff["Compute File Diff"]
    EnsureScopes["Ensure Space Scopes"]
    IngestPages["Ingest Pages (inline images into HTML)"]
    IngestAttachments["Ingest Remaining Attachments (non-images; images are inlined)"]
    Delete["Delete Removed Items"]
    Done(("Done"))
  end

  Start --> TenantSync
  InitScope --> Discover
  Discover --> Diff
  Diff --> EnsureScopes
  EnsureScopes --> IngestPages
  IngestPages --> IngestAttachments
  IngestPages -. images already inlined into pages are skipped .-> IngestAttachments
  IngestAttachments --> Delete
  Delete --> Done

classDef start fill:#FFA726,stroke:#EF6C00,stroke-width:2px,color:white
classDef process fill:#29B6F6,stroke:#0277BD,stroke-width:0px,color:white
classDef container fill:#F5F5F5,stroke:#BDBDBD,stroke-width:1px,stroke-dasharray: 5 5,color:#616161

class Start,Done start
class InitScope,Discover,Diff,EnsureScopes,IngestPages,IngestAttachments,Delete process
```

### Content Sync Flow

```mermaid
sequenceDiagram
    autonumber
    participant Scheduler
    participant Connector as Confluence Connector
    participant Confluence as Confluence API
    participant Unique as Unique Platform

    Note over Scheduler: Cron triggers (default: every 15 min)
    Scheduler->>Connector: Start sync cycle

    loop For each tenant
        Connector->>Unique: Initialize root scope & grant access

        Connector->>Confluence: Search pages by label (CQL)
        Confluence->>Connector: Labeled pages with attachments

        Connector->>Confluence: Get descendant pages (for ai-ingest-all labels)
        Confluence->>Connector: Descendant pages with attachments

        Connector->>Connector: Filter out skipped content types
        Connector->>Connector: Extract allowed attachments

        Connector->>Unique: Compute file diff (per space)
        Unique->>Connector: New, updated, deleted items

        Connector->>Unique: Ensure space scopes exist

        Connector->>Confluence: Fetch full page content
        Confluence->>Connector: Page HTML body
        opt Page has ac:image references to Confluence attachments
            opt Some references point to another page
                Connector->>Confluence: Look up target page by (spaceKey, title)
                Confluence->>Connector: Target page + its attachments
            end
            Connector->>Confluence: Download referenced image attachments
            Confluence->>Connector: Image streams
            Connector->>Connector: Inline images as base64 data URIs in page HTML
        end
        Connector->>Unique: Register, upload, finalize (single page artifact)

        Connector->>Confluence: Download remaining (non-image) attachment streams
        Confluence->>Connector: File stream
        Connector->>Unique: Register, upload, finalize

        Connector->>Unique: Delete removed items
    end

    Note over Connector: Sync cycle complete
```

See [Technical Reference](./technical/README.md) for detailed architecture and flow documentation.

### User Workflow

1. **Administrator Setup** (One-time)
   - Deploy the connector
   - Configure tenant YAML with Confluence credentials and Unique API endpoints
   - Set up the root scope in Unique

2. **Confluence Users** (Ongoing)
   - Apply the `ai-ingest` label to individual pages they want synchronized
   - Apply the `ai-ingest-all` label to a parent page to synchronize it and all its descendants

3. **Automated Processing**
   - The connector scans for labeled pages on the configured schedule
   - Discovers pages and their attachments
   - Computes a diff against previously ingested content
   - Ingests new and updated content, removes deleted content

## Limitations and Constraints

### Not Supported

- Real-time synchronization (periodic scanning only)
- Permission synchronization (content sync only)
- Confluence databases, whiteboards, and embeds (these content types are automatically skipped)
- Hierarchical scope structure (all pages from a space are placed in a single flat scope; sub-scopes mirroring the Confluence page tree are not created)

### Considerations

| Constraint | Impact | Mitigation |
|---|---|---|
| **Pages must be explicitly labeled** | No automatic sync of unlabeled content | Document the labeling workflow for end users |
| **Single ingestion mode (flat)** | All pages from a space are ingested into a single scope per space | Organize content into separate spaces if scope separation is needed |
| **Horizontal scaling not supported** | Single instance deployment | Adequate resource allocation; per-tenant concurrency tuning |
| **Concurrent sync prevention** | If a sync cycle for a tenant is still running when the next is scheduled, the new cycle is skipped | Adjust cron interval or concurrency settings for large instances |

## Related Documentation

- [FAQ](./faq.md) - Frequently asked questions and troubleshooting

### For IT Operators

- [Operator Guide](./operator/README.md) - Deployment, configuration, and operations
  - [Authentication](./operator/authentication.md) - Confluence and Unique auth setup
  - [Configuration](./operator/configuration.md) - Tenant config, environment variables, YAML settings
  - [Deployment](./operator/deployment.md) - Container and infrastructure setup

### Technical Reference

- [Technical Reference](./technical/README.md) - Architecture, flows, and design decisions
  - [Architecture](./technical/architecture.md) - System components and infrastructure
  - [Flows](./technical/flows.md) - Sync flows, file diff, discovery
  - [Permissions](./technical/permissions.md) - Confluence API and Unique permissions
  - [Security](./technical/security.md) - Security practices and compliance

## Standard References

- [Confluence Cloud REST API](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Data Center REST API](https://developer.atlassian.com/server/confluence/rest/) - Atlassian Confluence Data Center API documentation
- [Atlassian OAuth 2.0 (3LO) apps](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/) - Atlassian Cloud OAuth app setup (prerequisite for 2LO client credentials)
- [Confluence Query Language (CQL)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/) - CQL reference for content search queries
