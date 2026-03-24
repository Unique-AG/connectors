<!-- confluence-page-id:  -->
<!-- confluence-space-key: PUBDOC -->

# Directory Sync

Directory sync keeps the server's local copy of the user's Outlook folder structure in sync with Microsoft Graph. It runs on a 5-minute schedule using Graph delta queries.

It serves two purposes: enabling folder-based email search filtering, and tracking email movement between folders to handle soft and hard email deletion without relying on Graph delete notifications.

## Why Directory Sync Exists

The server discards `deleted` Microsoft Graph change notifications and instead handles email removal through two mechanisms:

**Individual email deletion:**
When a user deletes an email, Microsoft moves it to Deleted Items before permanent removal. This generates a `created` change notification for the Deleted Items folder (not a `deleted` notification for the original folder). Because Deleted Items is marked `ignoreForSync = true`, the server detects on this `created` event that the email has landed in an ignored folder and removes it from the Unique knowledge base.

**Entire folder deletion:**
When a folder itself is deleted, the directory sync detects the removal via its 5-minute delta sync and cleans up accordingly. No `deleted` change notification is needed.

This design means the server only needs to subscribe to `created` change notifications and rely on directory sync for structural changes — no `deleted` subscription is required.

## Search Filtering

The synced folder tree also powers the `list_folders` tool. The folder IDs it returns can be passed to the `directories` filter in `search_emails` to narrow results to a specific mailbox folder.

## How It Works

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    participant DirectoriesSync as Directory Sync Service
    participant MSGraph as Microsoft Graph API
    participant DB as PostgreSQL
    participant UniqueKB as Unique Knowledge Base

    Note over DirectoriesSync,DB: Initial scan (on module init)
    DirectoriesSync->>MSGraph: GET /me/mailFolders (full list)
    MSGraph->>DirectoriesSync: All folders with IDs, display names, parent IDs
    DirectoriesSync->>DB: Store folder tree in directories table
    DirectoriesSync->>UniqueKB: Register root scopes for synced folders

    Note over DirectoriesSync,DB: Ongoing delta sync (every 5 minutes)
    DirectoriesSync->>MSGraph: GET /me/mailFolders/delta?$deltaToken={token}
    MSGraph->>DirectoriesSync: Changed/added/removed folders since last sync
    DirectoriesSync->>DB: Update directories table
    DirectoriesSync->>DB: Store new deltaLink in directories_sync

    Note over DirectoriesSync,DB: Email moved to excluded folder
    DirectoriesSync->>DB: Detect email now in ignoreForSync folder
    DirectoriesSync->>UniqueKB: Remove email from knowledge base
```

## Schedule

| Event | Trigger |
|-------|---------|
| Initial scan | On module init after user connects |
| Ongoing delta sync | Every 5 minutes (cron) |

The `deltaLink` from each Graph delta response is stored in the `directories_sync` table and used on the next run to fetch only changed folders, keeping the sync efficient.

## Data Model

| Table | Purpose |
|-------|---------|
| `directories` | Folder tree — ID, display name, parent, `ignoreForSync` flag |
| `directories_sync` | Delta sync state — `deltaLink`, last sync timestamps |

## Relation to Subscription Management

Directory sync runs as long as the user has an active inbox connection. When `remove_inbox_connection` is called, directory sync data and the associated root scopes are removed from the Unique knowledge base along with the subscription.

## Related Documentation

- [Subscription Management](./subscription-management.md) - Inbox connection and subscription lifecycle
- [Live Catch-Up](./live-catchup.md) - Webhook-driven ingestion that runs alongside directory sync
- [Flows](./flows.md#directory-sync-flow) - Directory sync sequence diagram
- [Tools](./tools.md#list_folders) - `list_folders` tool reference
