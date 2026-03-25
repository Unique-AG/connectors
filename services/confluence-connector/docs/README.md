<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

> **Pre-release Notice:** The Confluence Connector v2 is currently in alpha (`2.0.0-alpha.4`). Configuration options and behavior may change before the stable release.

## Overview

The Confluence Connector is a service that synchronizes page content and file attachments from Confluence to the Unique knowledge base for RAG ingestion. It supports both Confluence Cloud and Confluence Data Center deployments.

For deployment, configuration, and operational details, see the [IT Operator Guide](./operator/README.md).

## Quick Summary

**What it does:** Synchronizes labeled Confluence pages and their attachments to Unique's AI knowledge base

**Supported platforms:** Confluence Cloud and Confluence Data Center

**Authentication:** OAuth 2.0 two-legged (Cloud and Data Center) or Personal Access Token (Data Center only)

**Scheduling:** Configurable automated scans (default: every 15 minutes)

**Multi-tenancy:** Multiple Confluence instances can be managed in a single deployment

**Deployment:** Kubernetes-based containerized application

## Requirements

### Confluence

| Requirement | Details |
|---|---|
| **Confluence Cloud** | Active instance with an Atlassian Cloud ID |
| **Confluence Data Center** | Self-hosted instance with REST API access |
| **Authentication** | OAuth 2.0 application credentials or a Personal Access Token (Data Center only) |
| **Permissions** | Read access to spaces and pages that should be synchronized |

**Prerequisites:**

- Ability to create and apply labels on Confluence pages
- An OAuth 2.0 application configured in Confluence (or a PAT for Data Center)
- A configured scope in the Unique platform to receive ingested content

### Authentication Methods

| Instance Type | Auth Method | Description |
|---|---|---|
| **Cloud** | OAuth 2.0 (2LO) | Client credentials flow via `https://api.atlassian.com/oauth/token` |
| **Data Center** | OAuth 2.0 (2LO) | Client credentials flow via the Data Center instance's token endpoint |
| **Data Center** | Personal Access Token | Static token-based authentication |

### Unique Platform Authentication

| Auth Mode | Description |
|---|---|
| **cluster_local** | For connectors running in the same Kubernetes cluster as Unique, using service headers (`x-company-id`, `x-user-id`) |
| **external** | For connectors running outside the cluster, using Zitadel OAuth credentials |

## Features

### Core Capabilities

**Label-Driven Page Discovery**

- Pages are discovered via configurable Confluence labels and ingested in HTML format (Confluence storage representation)
- The `ai-ingest` label (configurable per tenant) marks individual pages for synchronization
- The `ai-ingest-all` label (configurable per tenant) marks a page and all its descendant pages for synchronization
- The recommended convention is `ai-ingest` / `ai-ingest-all`, but operators must explicitly set these label names in their tenant configuration
- Only pages in global spaces are scanned (Cloud also includes collaboration spaces)

**Automatic Change Detection**

- File-diff mechanism compares discovered pages and attachments against the state stored in Unique
- Only new or modified items are ingested
- Deleted items are automatically removed from the knowledge base
- Safety checks prevent accidental full deletion when zero items are submitted or when the diff would delete all stored files

**Attachment Ingestion**

- File attachments on labeled pages are discovered and ingested alongside page content
- Attachment ingestion can be enabled or disabled
- Configurable file size limit (default: 200 MB)
- Configurable allowed file extensions (defaults listed below)

**Default Allowed Attachment Extensions**

| Extension | Format |
|---|---|
| `pdf` | PDF documents |
| `docx` | Microsoft Word |
| `xlsx` | Microsoft Excel |
| `ppt` | Microsoft PowerPoint (legacy) |
| `pptx` | Microsoft PowerPoint |
| `txt` | Plain text |
| `csv` | Comma-separated values |
| `html` | HTML files |

**Skipped Content Types**

The following Confluence content types are discovered but skipped during synchronization:

| Content Type | Reason |
|---|---|
| `database` | Not a standard page |
| `whiteboard` | Not a standard page |
| `embed` | Not a standard page |

**Scope Management**

- A root scope is configured per tenant
- Child scopes are automatically created for each Confluence space (using the space key as the scope name)
- Scopes inherit access from their parent

**Scheduled Synchronization**

- Sync runs on a configurable cron schedule (default: `*/15 * * * *`, every 15 minutes)
- An initial sync is triggered immediately on startup for each tenant
- Concurrent sync runs for the same tenant are prevented (the second run is skipped)

### Advanced Features

**Multi-Tenancy**

- Multiple Confluence instances (tenants) can be configured in a single deployment
- Each tenant has its own configuration, authentication, API client, and sync schedule
- Tenants are isolated via `AsyncLocalStorage`-based context

**Concurrency Control**

- Configurable page ingestion concurrency (default: 1)
- Configurable API rate limits for both Confluence and Unique APIs

**Observability**

- Structured JSON logging via pino
- OpenTelemetry metrics integration
- Prometheus metrics endpoint

**Security**

- OAuth 2.0 two-legged (2LO) authentication for Cloud and Data Center
- Personal Access Token (PAT) support for Data Center
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
    IngestPages["Ingest New/Updated Pages"]
    IngestAttachments["Ingest New/Updated Attachments"]
    Delete["Delete Removed Items"]
    Done(("Done"))
  end

  Start --> TenantSync
  InitScope --> Discover
  Discover --> Diff
  Diff --> EnsureScopes
  EnsureScopes --> IngestPages
  IngestPages --> IngestAttachments
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
        Connector->>Unique: Register, upload, finalize

        Connector->>Confluence: Download attachment stream
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
- Recursive/hierarchical ingestion mode (only flat mode is available)

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
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Atlassian OAuth 2.0 (2LO)](https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/) - Atlassian OAuth documentation
- [Confluence Query Language (CQL)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/) - CQL reference for content search queries
