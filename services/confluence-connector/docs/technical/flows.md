<!-- confluence-page-id: -->
<!-- confluence-space-key: PUBDOC -->

## Content Sync Flow

The content sync flow runs periodically (default: every 15 minutes) to synchronize labeled Confluence pages and their attachments to Unique.

### Overview

```mermaid
flowchart TB
    subgraph Trigger["Trigger"]
        Scheduler["Scheduler<br/>(cron)"]
    end

    subgraph Initialization["Initialization"]
        Guard["Re-entrancy guard"]
        Scope["Initialize root scope"]
    end

    subgraph Discovery["Discovery Phase"]
        SearchCQL["CQL label search"]
        Descendants["Fetch descendants<br/>(ingestAllLabel pages)"]
        Deduplicate["Deduplicate pages"]
        FilterTypes["Filter skipped content types"]
        ExtractAttachments["Extract attachments<br/>(if enabled)"]
    end

    subgraph Processing["Processing Phase"]
        Diff["Per-space file diff<br/>(Unique Platform)"]
        Validate["Safety checks"]
    end

    subgraph Sync["Sync Phase"]
        EnsureScopes["Ensure space scopes"]
        FetchContent["Fetch page content"]
        IngestPages["Ingest pages"]
        IngestAttachments["Ingest attachments"]
        Delete["Delete removed items"]
    end

    Scheduler --> Guard
    Guard --> Scope
    Scope --> SearchCQL
    SearchCQL --> Descendants
    Descendants --> Deduplicate
    Deduplicate --> FilterTypes
    FilterTypes --> ExtractAttachments
    ExtractAttachments --> Diff
    Diff --> Validate
    Validate --> EnsureScopes
    EnsureScopes --> FetchContent
    FetchContent --> IngestPages
    IngestPages --> IngestAttachments
    IngestAttachments --> Delete
```

### Sequence Diagram

The connector is **stateless** -- it does not maintain local state between sync cycles. Change detection is performed by the Unique platform's file diff API, called once per Confluence space.

```mermaid
sequenceDiagram
    autonumber
    participant Scheduler
    participant Connector as Confluence Connector
    participant Confluence as Confluence API
    participant Unique as Unique Platform

    Note over Scheduler: Cron triggers<br/>(default: every 15 min)
    Scheduler->>Connector: Start sync cycle

    alt Sync already in progress
        Note over Connector: Skip (re-entrancy guard)
    end

    Connector->>Unique: Initialize root scope<br/>(grant access, verify exists)

    rect rgb(200, 210, 240)
        Note over Connector,Confluence: Discovery Phase
        Connector->>Confluence: CQL search: pages with<br/>ingestSingleLabel OR ingestAllLabel
        Confluence->>Connector: Labeled pages<br/>(with inline attachments)

        opt Pages with ingestAllLabel
            Connector->>Confluence: CQL ancestor query<br/>(batches of 100 root IDs)
            Confluence->>Connector: Descendant pages
        end

        Note over Connector: Deduplicate, filter skipped types,<br/>extract attachments (if enabled)
    end

    rect rgb(200, 235, 200)
        Note over Connector,Unique: Processing Phase
        loop For each Confluence space
            Connector->>Unique: POST file diff<br/>(pages + attachments per space)
            Unique->>Connector: newFiles, updatedFiles,<br/>deletedFiles, movedFiles
            Note over Connector: Safety checks:<br/>abort if accidental full deletion<br/>(movedFiles are not processed)
        end
    end

    rect rgb(240, 210, 200)
        Note over Connector,Unique: Sync Phase — Ingestion
        Connector->>Unique: Ensure space scopes

        loop For each new/updated page (concurrency-limited)
            Connector->>Confluence: GET page by ID<br/>(body.storage)
            Confluence->>Connector: Page HTML content
            Connector->>Unique: Register content
            Connector->>Unique: PUT buffer upload (text/html)
            Connector->>Unique: Finalize ingestion
        end

        loop For each new/updated attachment (concurrency-limited)
            Connector->>Unique: Register content
            Connector->>Confluence: Download attachment
            Confluence->>Connector: File stream
            Connector->>Unique: PUT stream upload (original media type)
            Connector->>Unique: Finalize ingestion
        end
    end

    opt Deleted items exist
        Connector->>Unique: Resolve content keys to IDs
        Connector->>Unique: Delete content by IDs
    end

    Note over Connector: Sync cycle complete
```

### Scope Hierarchy

The connector manages a two-level scope hierarchy:

1. **Root scope** -- Must pre-exist in the Unique platform. Configured via `ingestion.scopeId`. The connector grants itself access at initialization.
2. **Space scopes** -- Created automatically as children of the root scope, one per Confluence space key. Access is inherited from the root scope.

## Discovery Phase

Pages are discovered through a CQL-based label search, then attachments are optionally extracted from the already-fetched page objects.

### Discovery Sequence

```mermaid
flowchart TB
    CQL["CQL search:<br/>ingestSingleLabel OR ingestAllLabel"] --> LabeledPages["Labeled pages<br/>(with inline attachments)"]
    LabeledPages --> FilterIngestAll["Filter pages with ingestAllLabel"]
    FilterIngestAll --> HasIngestAll{"Any ingestAll<br/>pages?"}
    HasIngestAll -->|Yes| FetchDescendants["CQL ancestor query<br/>(batches of 100)"]
    HasIngestAll -->|No| Merge
    FetchDescendants --> Merge["Merge & deduplicate<br/>(by page ID)"]
    Merge --> MapPages["Map to discovered pages"]
    MapPages --> LimitCheck{"maxItemsToScan<br/>reached?"}
    LimitCheck -->|Yes| Stop["Stop accepting"]
    LimitCheck -->|No| SkipTypes{"Content type<br/>check"}
    SkipTypes -->|"database, whiteboard, embed"| Skip["Skip"]
    SkipTypes -->|"page, blogpost, folder"| Continue["Continue"]

    Continue --> AttachmentsEnabled{"Attachments<br/>enabled?"}
    AttachmentsEnabled -->|No| Done["Return pages only"]
    AttachmentsEnabled -->|Yes| ExtractAttachments["Extract attachments<br/>from page objects"]
    ExtractAttachments --> FilterAttachments["Filter by extension<br/>and file size"]
    FilterAttachments --> RemainingCapacity{"Remaining capacity<br/>(maxItemsToScan - pages)?"}
    RemainingCapacity --> Done2["Return pages + attachments"]
```

### CQL Queries

The connector uses Confluence Query Language (CQL) to discover pages. The exact CQL differs by instance type:

| Instance Type | Space Type Filter | CQL Template |
|---|---|---|
| Cloud | `space.type=global OR space.type=collaboration` | `((label="{ingestSingleLabel}") OR (label="{ingestAllLabel}")) AND ({spaceTypeFilter}) AND type != attachment` |
| Data Center | `space.type=global` | Same template, different space type filter |

The space type filter varies by instance type. See the [Configuration Guide](../operator/configuration.md#space-scanning) for details on which space types are scanned per platform.

The `type != attachment` clause excludes attachments from top-level CQL results since they are fetched via the `expand=children.attachment` parameter on the page objects themselves.

### Descendant Discovery

Pages labeled with `ingestAllLabel` trigger a descendant search:

1. Collect all page IDs that carry the `ingestAllLabel`
2. Batch IDs into groups of 100
3. For each batch, execute CQL: `ancestor IN ({batch}) AND type != attachment`
4. Deduplicate results with labeled pages by page ID

### Attachment Extraction

When `attachments.mode` is `enabled` (default), attachments are extracted from the already-fetched page objects -- no additional API calls are made during extraction. Attachments were inlined by the `expand=children.attachment` parameter during the CQL search.

An attachment is accepted if:
- Its file extension is in the `allowedExtensions` list (default: `pdf`, `docx`, `xlsx`, `ppt`, `pptx`, `txt`, `csv`, `html`)
- Its file size does not exceed `maxFileSizeMb` (default: 200 MB)
- The `maxItemsToScan` capacity has not been exhausted (pages count first, attachments use remaining capacity)

If a page has more than 25 attachments (the Confluence inline limit), additional attachments are fetched:
- **Cloud**: Uses the v2 REST API (`/wiki/api/v2/pages/{pageId}/attachments`) because the v1 pagination endpoint returns 410 Gone
- **Data Center**: Follows v1 `_links.next` pagination links

### Content Type Ingestion Map

The connector uses label-based discovery via CQL. After fetching, it skips three content types: database, whiteboard, and embed.

Content that passes the filter has its `body.storage` HTML extracted and ingested. Items with empty bodies are skipped. Descendants of skipped content types (such as sub-pages under a database) are still discovered and ingested.

#### Confluence Cloud

| Content Type | Ingested? | Body Available via API? | Notes |
|---|---|---|---|
| Page | **Yes** | Yes (`body.storage` / ADF) | Primary content type. Full body ingestion. |
| Blog Post | **Yes** | Yes (`body.storage` / ADF) | Treated identically to pages by the connector. |
| Attachment | **Yes** (conditional) | No (binary) | Only when `attachments.mode=enabled`. Filtered by extension and size. |
| Whiteboard | **No** | No (no body via API) | Explicitly skipped. API returns no body content. Descendants are still discovered. |
| Database | **No** | No (structured data, not exposed) | Explicitly skipped. No body via API. Descendants (sub-pages) are still discovered and ingested. |
| Embed / Smart Link | **No** | No (only has `embedUrl`) | Explicitly skipped. Only contains a URL reference, no renderable body. |
| Folder | **No** (effectively) | No (organizational container) | Not explicitly skipped, but has no body -- skipped by the empty-body filter. Descendants are still discovered. |
| Comment (inline/footer) | **No** | Yes (`body.storage` / ADF) | Not discovered -- comments do not appear in label/ancestor CQL results. |
| Live Doc (page subtype) | **Yes** (as page) | Yes (`body.storage` / ADF) | Subtype of page. Passes through as a regular page. |
| Custom Content (app-defined) | **No** | Yes (`body.storage`) | Not discovered -- uses `ac:key:type` format, not matched by standard CQL. |
| Task (standalone) | **No** | Yes (`body.storage` / ADF) | Not a CQL-searchable content type. Only accessible via `/tasks` v2 endpoint. |

#### Confluence Data Center

| Content Type | Exists in DC? | Ingested? | Notes |
|---|---|---|---|
| Page | Yes | **Yes** | Primary content type. Full body ingestion (storage format / XHTML). |
| Blog Post | Yes | **Yes** | Treated identically to pages by the connector. |
| Attachment | Yes | **Yes** (conditional) | Only when `attachments.mode=enabled`. Uses v1 pagination (`_links.next`). |
| Comment (inline/footer) | Yes | **No** | Not discovered -- comments do not appear in label/ancestor CQL results. |
| Custom Content (plugin-defined) | Yes | **No** | Accessed via plugin-specific REST APIs, not standard `/rest/api/content`. |
| Whiteboard, Database, Embed, Folder, Live Doc | No | N/A | Cloud-only features. Do not exist in Data Center. |

## File Diff Mechanism

The connector uses the Unique platform's server-side file diff API to detect changes between sync cycles. The connector does **not** compute local content hashes -- instead, it sends each item's `key`, `url`, and `updatedAt` timestamp to the diff endpoint, which returns categorized results. The diff is called once per Confluence space.

### State Comparison

```mermaid
flowchart TB
    subgraph Input["Input"]
        ConfluenceState["Confluence State<br/>(current scan: key, url, updatedAt per item)"]
    end

    subgraph Comparison["Server-Side Diff"]
        Compare["POST file diff<br/>(Unique Platform)"]
    end

    subgraph Output["Output"]
        New["New Items"]
        Modified["Updated Items"]
        Moved["Moved Items"]
        Deleted["Deleted Items"]
    end

    ConfluenceState --> Compare
    Compare --> New
    Compare --> Modified
    Compare --> Moved
    Compare --> Deleted
```

### Change Detection Logic

```mermaid
flowchart TB
    Start["Collect all discovered items<br/>from Confluence"] --> BuildList["Build item list<br/>(key, url, updatedAt)"]
    BuildList --> CallDiff["POST file diff"]

    CallDiff --> NewFiles["newFiles: keys not previously known"]
    CallDiff --> UpdatedFiles["updatedFiles: keys with changed updatedAt"]
    CallDiff --> MovedFiles["movedFiles: keys that were relocated"]
    CallDiff --> DeletedFiles["deletedFiles: previously known keys no longer in list"]

    NewFiles --> Ingest["Fetch & ingest"]
    UpdatedFiles --> Ingest
    DeletedFiles --> Delete["Delete from Unique"]
```

### File Diff Item Attributes

Each item sent to the diff API contains:

| Attribute | Description | Used For |
|---|---|---|
| `key` | Unique key identifying the item (derived from page and attachment IDs) | Identity and change tracking |
| `url` | Confluence URL of the page or attachment | Location tracking |
| `updatedAt` | Last modification timestamp from Confluence | Change detection |

## Ingestion Pipeline

For details on the 3-step ingestion pipeline (register, upload, finalize), key format, and sourceKind values, see [Technical Reference - Ingestion Pipeline](./README.md#ingestion-pipeline) and [Technical Reference - v1-Compatible Key Format](./README.md#v1-compatible-key-format).

### Page Ingestion

For each new or updated page:

1. **Fetch content** -- The connector retrieves the full page content (HTML storage representation). The page is skipped if it is not found, if fetching fails, or if the page body is empty.
2. **Extract labels** -- Confluence labels are extracted from the page, excluding the configured sync labels. Labels are sorted alphabetically for deterministic ordering.
3. **Register** -- Sends metadata to the Unique ingestion API.
4. **Upload** -- The page body (Confluence storage format HTML) is uploaded to Unique.
5. **Finalize** -- Triggers downstream processing in Unique.

If any step fails for a page, the error is logged and that page is skipped. Other pages continue processing.

### Attachment Ingestion

For each new or updated attachment:

1. **Skip zero-byte** -- Attachments with zero file size are skipped.
2. **Register** -- Sends metadata to the Unique ingestion API.
3. **Download** -- Streams the attachment from Confluence.
4. **Upload** -- The stream is uploaded to Unique with the original content type and content length.
5. **Finalize** -- Triggers downstream processing in Unique.

If any step fails, the stream is destroyed and the error is logged. Other attachments continue processing.

### Deletion

Deleted items identified by the file diff are processed after ingestion:

1. Build content keys from `{partialKey}/{id}` for each deleted item
2. Resolve keys to content IDs
3. Delete content by IDs

If no content is found for the given keys, a warning is logged and no deletion occurs.

### Concurrency and Progress

Ingestion concurrency is controlled by `processing.concurrency` (default: 1). Pages are ingested first, then attachments -- not in parallel. All items in a batch are attempted even if some fail.

Progress is logged periodically. After all items complete, a summary is logged with the total, succeeded, and failed counts.

## Error Handling

### Error Handling Strategy

The connector applies scenario-specific behavior to keep sync cycles stable:

| Scenario | Typical Cause | Connector Behavior |
|---|---|---|
| Sync already in progress | Overlapping cron triggers or long-running sync | Skip the cycle entirely (re-entrancy guard) |
| Root scope not found | Misconfigured `scopeId` or scope deleted | Abort the entire sync cycle |
| Accidental full deletion detected | Bug in page fetching or key format change | Abort the entire tenant sync cycle (see [Safety Checks](#safety-checks)) |
| Page fetch failure | Page deleted between discovery and content fetch, transient API error | Log error, skip the page, continue other pages |
| Page not found | Page deleted between discovery and content fetch | Log warning, skip the page |
| Page with empty body | Page has no content (e.g., newly created) | Log, skip the page |
| Attachment with zero bytes | Empty attachment | Log, skip the attachment |
| Page ingestion failure | Upload error, registration error | Log error, skip the page |
| Attachment ingestion failure | Download error, upload error | Destroy stream, log error, skip the attachment |
| Content deletion failure | Unique API error | Log error, return 0 deleted count |
| Unhandled sync error | Unexpected exception | Caught at top level, logged, scanning flag reset |

### Retry Logic

```mermaid
flowchart TB
    Request["API Request<br/>(rate-limited)"] --> Dispatch["HTTP dispatch<br/>with retry + redirect"]
    Dispatch --> Response{"Status code<br/>2xx?"}
    Response -->|Yes| Continue["Return response"]
    Response -->|No| RetryCheck{"Retryable?"}
    RetryCheck -->|Yes| Dispatch
    RetryCheck -->|No| HandleError["Throw error<br/>with status + body"]
```

Transient HTTP errors are retried automatically with backoff. Requests follow redirects (up to 10 redirections). Non-2xx responses that exhaust retries are thrown as errors with the status code and response content.

## Related Documentation

- [Technical Reference](./README.md) - Architecture overview, key concepts, ingestion pipeline
- [Architecture](./architecture.md) - System components and infrastructure
- [Configuration](../operator/configuration.md) - Scheduler and processing settings

## Standard References

- [Confluence Cloud REST API](https://developer.atlassian.com/cloud/confluence/rest/v1/intro/) - Atlassian Confluence Cloud API documentation
- [Confluence Data Center REST API](https://docs.atlassian.com/ConfluenceServer/rest/latest/) - Atlassian Confluence Data Center API documentation
- [Confluence Query Language (CQL)](https://developer.atlassian.com/cloud/confluence/advanced-searching-using-cql/) - CQL reference for content search queries
