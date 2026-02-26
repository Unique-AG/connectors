<!-- confluence-page-id: 1952546867 -->
<!-- confluence-space-key: PUBDOC -->


## Content Sync Flow

The content sync flow runs periodically (default: every 15 minutes) to synchronize flagged documents from SharePoint to Unique.

### Overview

```mermaid
flowchart TB
    subgraph Trigger["Trigger"]
        Scheduler["Scheduler<br/>(cron)"]
    end

    subgraph Discovery["Discovery Phase"]
        FetchSites["Fetch Configured Sites"]
        FetchDrives["Fetch Document Libraries"]
        FetchItems["Fetch Items with Sync Column"]
    end

    subgraph Processing["Processing Phase"]
        Filter["Filter Flagged Items"]
        Diff["Compare with Local State"]
        Download["Download Content"]
    end

    subgraph Ingestion["Ingestion Phase"]
        Upload["Upload to Unique"]
        UpdateState["Update Local State"]
    end

    Scheduler --> FetchSites
    FetchSites --> FetchDrives
    FetchDrives --> FetchItems
    FetchItems --> Filter
    Filter --> Diff
    Diff --> Download
    Download --> Upload
    Upload --> UpdateState
```

### Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    participant Scheduler
    participant Connector as SharePoint Connector
    participant Graph as Microsoft Graph API
    participant Unique as Unique Platform

    Note over Scheduler: Cron triggers (default: every 15 min)
    Scheduler->>Connector: Start sync cycle

    loop For each configured site
        Connector->>Graph: GET /sites/{siteId}
        Graph->>Connector: Site metadata

        Connector->>Graph: GET /sites/{siteId}/drives
        Graph->>Connector: Document libraries

        loop For each drive
            Connector->>Graph: GET /drives/{driveId}/root/children<br/>?$expand=listItem($expand=fields)
            Graph->>Connector: Items with custom fields

            Note over Connector: Filter items where<br/>sync column = Yes

            Connector->>Connector: Compare with local state<br/>(detect new, modified, deleted)

            par Process new/modified files
                Connector->>Graph: GET /drives/{driveId}/items/{itemId}/content
                Graph->>Connector: File content (stream)
                Connector->>Unique: POST /ingestion/files
                Unique->>Connector: Ingestion confirmation
            and Remove deleted files
                Connector->>Unique: DELETE /scopes/{scopeId}/files/{fileId}
                Unique->>Connector: Deletion confirmation
            end

            Connector->>Connector: Update local state
        end
    end

    Note over Connector: Sync cycle complete
```

## Permission Sync Flow

When enabled, the permission sync flow synchronizes SharePoint permissions to Unique.

### Overview

```mermaid
flowchart TB
    subgraph Trigger["Trigger"]
        SyncCycle["Content Sync Cycle"]
    end

    subgraph FetchPerms["Fetch Permissions"]
        ItemPerms["Get Item Permissions<br/>(Graph API)"]
        ResolveGroups["Resolve Groups"]
    end

    subgraph GroupResolution["Group Resolution"]
        EntraGroups["Entra ID Groups<br/>(Graph API)"]
        SPGroups["SharePoint Groups<br/>(SP REST API)"]
    end

    subgraph UserMapping["User Mapping"]
        MapUsers["Map to Unique Users"]
        UpdatePerms["Update Unique Permissions"]
    end

    SyncCycle --> ItemPerms
    ItemPerms --> ResolveGroups
    ResolveGroups --> EntraGroups
    ResolveGroups --> SPGroups
    EntraGroups --> MapUsers
    SPGroups --> MapUsers
    MapUsers --> UpdatePerms
```

### Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    participant Connector as SharePoint Connector
    participant Graph as Microsoft Graph API
    participant SPREST as SharePoint REST API
    participant Unique as Unique Platform

    Note over Connector: Permission sync triggered<br/>after content sync

    loop For each synced file
        Connector->>Graph: GET /drives/{driveId}/items/{itemId}/permissions
        Graph->>Connector: Permission entries

        loop For each permission entry
            alt Entra ID Group
                Connector->>Graph: GET /groups/{groupId}/members
                Graph->>Connector: Group members
            else SharePoint Site Group
                Connector->>SPREST: GET /_api/web/sitegroups/getById({id})/users
                SPREST->>Connector: Site group members
            else Direct User
                Note over Connector: Use user principal directly
            end
        end

        Connector->>Unique: GET /users?email={email}
        Unique->>Connector: Unique user IDs

        Connector->>Unique: PUT /scopes/{scopeId}/permissions
        Unique->>Connector: Permissions updated
    end
```

### Permission Types

The connector handles different permission sources:

| Source | API | Resolution |
|--------|-----|------------|
| Direct user grant | Graph API | Map email to Unique user |
| Entra ID (Azure AD) group | Graph API | Expand group members |
| SharePoint site group | SharePoint REST | Expand group members |
| Sharing link | Graph API | Extract grantees |

### Group Visibility Requirement

IMPORTANT: For SharePoint site groups, the connector must be able to read group members. If "Who can view the membership of the group?" is **not** set to "Everyone", the connector cannot read members.

**Mitigation:**

- Set group visibility to "Everyone"
- Add app principal as group member/owner
- Grant Full Control to app principal

### Public Site and Tenant-Wide Groups

For public SharePoint sites, permissions can include tenant-wide principals such as `Everyone` or `Everyone except external users`. The connector does not expand these principals for sync. As a result, content may be accessible in SharePoint while corresponding tenant-wide visibility is not mirrored in Unique permissions.

## File Diff Mechanism

The connector maintains local state to detect changes between sync cycles.

### State Comparison

```mermaid
flowchart TB
    subgraph Input["Input"]
        SharePointState["SharePoint State<br/>(current scan)"]
        LocalState["Local State<br/>(previous scan)"]
    end

    subgraph Comparison["Comparison"]
        Compare["Compare States"]
    end

    subgraph Output["Output"]
        New["New Files<br/>(in SP, not in local)"]
        Modified["Modified Files<br/>(hash changed)"]
        Deleted["Deleted Files<br/>(in local, not in SP)"]
        Unchanged["Unchanged Files<br/>(skip processing)"]
    end

    SharePointState --> Compare
    LocalState --> Compare
    Compare --> New
    Compare --> Modified
    Compare --> Deleted
    Compare --> Unchanged
```

### Change Detection Logic

```mermaid
flowchart TB
    Start["For each item<br/>in SharePoint"] --> InLocal{"In local<br/>state?"}

    InLocal -->|No| NewFile["Mark as NEW"]
    InLocal -->|Yes| CheckHash{"Content hash<br/>changed?"}

    CheckHash -->|Yes| ModifiedFile["Mark as MODIFIED"]
    CheckHash -->|No| CheckMeta{"Metadata<br/>changed?"}

    CheckMeta -->|Yes| ModifiedFile
    CheckMeta -->|No| UnchangedFile["Mark as UNCHANGED"]

    subgraph LocalOnly["Process local-only items"]
        LocalItem["For each item<br/>in local state"] --> InSP{"Still in<br/>SharePoint?"}
        InSP -->|No| CheckFlag{"Was sync<br/>column = Yes?"}
        CheckFlag -->|No| DeletedFile["Mark as DELETED"]
        CheckFlag -->|Yes, now No| UnflaggedFile["Mark as UNFLAGGED<br/>(treat as deleted)"]
        InSP -->|Yes| AlreadyProcessed["Already processed"]
    end
```

### State Attributes

| Attribute | Description | Used For |
|-----------|-------------|----------|
| `itemId` | SharePoint item ID | Unique identifier |
| `driveId` | Document library ID | Scope identification |
| `contentHash` | SHA-256 of content | Change detection |
| `lastModified` | Last modification timestamp | Change detection |
| `syncColumnValue` | Current flag state | Unflag detection |
| `uniqueFileId` | Unique platform file ID | Deletion |

## ASPX Page Processing

SharePoint site pages (`.aspx`) require special handling:

### ASPX Sync Flow

```mermaid
sequenceDiagram
    autonumber
    participant Connector
    participant Graph as Microsoft Graph API
    participant Unique

    Connector->>Graph: GET /sites/{siteId}/lists<br/>?$filter=displayName eq 'Site Pages'
    Graph->>Connector: SitePages list ID

    Connector->>Graph: GET /sites/{siteId}/lists/{listId}/items<br/>?$expand=fields
    Graph->>Connector: ASPX page items

    loop For each flagged ASPX page
        Connector->>Graph: GET /sites/{siteId}/lists/{listId}/items/{itemId}<br/>?$expand=fields($select=CanvasContent1,WikiField)
        Graph->>Connector: Page content (HTML)

        Connector->>Connector: Extract text from HTML
        Connector->>Unique: POST /ingestion/files<br/>(as text/html)
        Unique->>Connector: Ingestion confirmation
    end
```

### Content Extraction

ASPX pages contain structured content in special fields:

| Field | Content Type | Description |
|-------|--------------|-------------|
| `CanvasContent1` | JSON/HTML | Modern page web parts |
| `WikiField` | HTML | Classic wiki content |

The connector extracts text content from these fields for ingestion.

## Error Handling

### Error Handling Strategy

The connector applies scenario-specific behavior to keep sync cycles stable while avoiding incorrect permission or content updates:

| Scenario | Typical Cause | Connector Behavior |
|----------|---------------|--------------------|
| Authentication/configuration error | Invalid certificate, wrong tenant/app configuration | Fail the current cycle early, log actionable error, require operator fix |
| Transient API/network error | 429/5xx, temporary network failures | Retry with backoff up to retry limit, then skip affected item and continue |
| Permission denied (`403`) | Missing site/library grant or group visibility restriction | Skip affected item/permission sync path and continue remaining work |
| Not found (`404`) | Item deleted/renamed or stale state | Treat as deleted where applicable and reconcile local state |
| Malformed/unsupported content | Corrupt file or parser failure | Log item-level error, skip item, continue cycle |

### Retry Logic

```mermaid
flowchart TB
    Request["API Request"] --> Response{"Success?"}
    Response -->|Yes| Continue["Continue Processing"]
    Response -->|No| CheckRetry{"Retryable<br/>error?"}

    CheckRetry -->|Yes| Backoff["Exponential Backoff"]
    Backoff --> RetryCount{"Retry<br/>count < max?"}
    RetryCount -->|Yes| Request
    RetryCount -->|No| Fail["Log Error<br/>Skip Item"]

    CheckRetry -->|No| Fail
```

### Retryable Errors

| Error Code | Description | Retry |
|------------|-------------|-------|
| 429 | Rate limited | Yes (with backoff) |
| 500 | Server error | Yes |
| 502 | Bad gateway | Yes |
| 503 | Service unavailable | Yes |
| 504 | Gateway timeout | Yes |
| 401 | Unauthorized | Yes (refresh token) |

### Non-Retryable Errors

| Error Code | Description | Action |
|------------|-------------|--------|
| 400 | Bad request | Skip item, log error |
| 403 | Forbidden | Skip item, log error |
| 404 | Not found | Mark as deleted |

## Related Documentation

- [Architecture](./architecture.md) - System components and infrastructure
- [Permissions](./permissions.md) - Required API permissions
- [Configuration](../operator/configuration.md) - Scheduler and processing settings

## Standard References

- [Microsoft Graph API - DriveItem](https://learn.microsoft.com/en-us/graph/api/resources/driveitem) - DriveItem resource
- [Microsoft Graph API - Permissions](https://learn.microsoft.com/en-us/graph/api/driveitem-list-permissions) - List permissions
- [SharePoint REST API](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/get-to-know-the-sharepoint-rest-service) - REST service overview
