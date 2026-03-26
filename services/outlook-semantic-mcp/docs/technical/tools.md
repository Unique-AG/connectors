<!-- confluence-page-id: 2061238285 -->
<!-- confluence-space-key: PUBDOC -->

# Tools

The Outlook Semantic MCP Server exposes 10 MCP tools available to all users, plus 4 debug-mode tools only exposed when `MCP_DEBUG_MODE=enabled` is set on the server.

!!! warning "Debug-Mode Tools"
    `run_full_sync`, `pause_full_sync`, `resume_full_sync`, and `restart_full_sync` are **only available when `MCP_DEBUG_MODE=enabled`** is configured. They are intended for operators diagnosing sync issues — they do not appear in the tool list for standard deployments.

## Tool Overview

| Tool | Category | Mutating | Debug Only |
|------|----------|----------|------------|
| [`search_emails`](#search_emails) | Email Search | No | No |
| [`open_email_by_id`](#open_email_by_id) | Email Search | No | No |
| [`create_draft_email`](#create_draft_email) | Draft Creation | Yes | No |
| [`lookup_contacts`](#lookup_contacts) | Contact Lookup | No | No |
| [`list_categories`](#list_categories) | Mailbox Utilities | No | No |
| [`list_folders`](#list_folders) | Mailbox Utilities | Yes (refreshes folder cache) | No |
| [`verify_inbox_connection`](#verify_inbox_connection) | Subscription Management | No | No |
| [`reconnect_inbox`](#reconnect_inbox) | Subscription Management | Yes | No |
| [`remove_inbox_connection`](#remove_inbox_connection) | Subscription Management | Yes | No |
| [`sync_progress`](#sync_progress) | Sync Monitoring | No | No |
| [`run_full_sync`](#run_full_sync) | Full Sync Control (debug only) | Yes | **Yes** |
| [`pause_full_sync`](#pause_full_sync) | Full Sync Control (debug only) | Yes | **Yes** |
| [`resume_full_sync`](#resume_full_sync) | Full Sync Control (debug only) | Yes | **Yes** |
| [`restart_full_sync`](#restart_full_sync) | Full Sync Control (debug only) | Yes | **Yes** |

**Mutating** means the tool writes data to at least one of the following:

- **Outlook mailbox** — creates or modifies data in Microsoft Graph (e.g. a draft email or a webhook subscription)
- **Internal database** — persists or removes state managed by this server (e.g. subscription records, sync state, folder cache)
- **Unique knowledge base** — indexes or removes email content from the knowledge base used for search

| Tool | What it mutates |
|------|----------------|
| `create_draft_email` | Creates a draft message in the user's Outlook mailbox via Microsoft Graph |
| `list_folders` | Refreshes the folder cache in the internal database by re-fetching the folder tree from Microsoft Graph |
| `reconnect_inbox` | Creates or renews the Microsoft Graph webhook subscription and writes the subscription record to the internal database |
| `remove_inbox_connection` | Cancels the Microsoft Graph webhook subscription and deletes the subscription record, folder cache, and root scope from the internal database |
| `run_full_sync` | Triggers ingestion of all mailbox emails into the Unique knowledge base and updates sync state in the internal database |
| `pause_full_sync` | Updates the sync state to `paused` in the internal database |
| `resume_full_sync` | Updates the sync state to resume ingestion in the internal database |
| `restart_full_sync` | Resets sync state in the internal database and re-triggers full ingestion into the Unique knowledge base |

---

## Email Search

### `search_emails`

Search emails semantically with optional structured filters. Results are returned from the Unique knowledge base — no live Microsoft Graph call is made per query. Use `sync_progress` if the response includes a `syncWarning`, as results may be incomplete.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `search` | string | Yes | Search query |
| `limit` | number (40–100) | No | Maximum results to return. Default: 40 |
| `conditions` | array | No | Filter conditions. Multiple condition objects are combined with OR; fields within a single condition are combined with AND. Each condition must have at least one field. |

Each object in `conditions` may include the following fields. All condition fields use an operator-wrapped format:

| Field | Type | Description |
|-------|------|-------------|
| `dateFrom` | `{ value: string, operator }` | ISO 8601 date — emails received on or after this date |
| `dateTo` | `{ value: string, operator }` | ISO 8601 date — emails received on or before this date |
| `fromSenders` | `{ value: string, operator }` or `{ value: string[], operator: "in" \| "notIn" \| "containsAny" }` | Filter by sender — accepts full email addresses or partial strings (e.g. `"@example.com"`). Prefer `containsAny` when matching a list of emails. |
| `toRecipients` | `{ value: string, operator }` or `{ value: string[], operator: "in" \| "notIn" \| "containsAny" }` | Filter by To recipient — accepts full email addresses or partial strings. Prefer `containsAny` when matching a list of emails. |
| `ccRecipients` | `{ value: string, operator }` or `{ value: string[], operator: "in" \| "notIn" \| "containsAny" }` | Filter by CC recipient — accepts full email addresses or partial strings. Prefer `containsAny` when matching a list of emails. |
| `directories` | `{ value: string[], operator: "in" \| "notIn" }` | Folder IDs (from `list_folders`) or system names: `"Inbox"`, `"Sent Items"`, `"Drafts"`, `"Archive"`, `"Outbox"`, `"Clutter"`, `"Conversation History"` |
| `hasAttachments` | `{ value: boolean, operator }` | Filter to emails with or without attachments |
| `categories` | `{ value: string, operator }` or `{ value: string[], operator: "in" \| "notIn" }` | Category labels (from `list_categories`) |

**Available operators:**

- Singular operators: `equals`, `notEquals`, `greaterThan`, `greaterThanOrEqual`, `lessThan`, `lessThanOrEqual`, `contains`, `notContains`, `isNull`, `isNotNull`, `isEmpty`, `isNotEmpty`
- Array operators: `in`, `notIn`, `containsAny` (email fields only — expands to OR of `contains` filters)

**Return shape:**

```typescript
{
  success: boolean;
  status?: string;
  message?: string;
  syncWarning?: string;         // present if sync is incomplete
  searchSummary?: string;
  results?: Array<{
    id: string;                 // pass to open_email_by_id
    emailId: string;
    folderId: string;
    title: string;
    from: string;
    receivedDateTime?: string | null;
    text: string;               // matched passage
    outlookWebLink?: string;
    url?: string;
  }>;
}
```

**Example:**

```json
{
  "search": "quarterly report from Alice",
  "conditions": [
    {
      "fromSenders": { "value": "alice@example.com", "operator": "equals" },
      "dateFrom": { "value": "2024-01-01T00:00:00Z", "operator": "greaterThanOrEqual" },
      "dateTo": { "value": "2024-03-31T23:59:59Z", "operator": "lessThanOrEqual" },
      "directories": { "value": ["Inbox"], "operator": "in" }
    }
  ],
  "limit": 40
}
```

This searches for emails from `alice@example.com` in Q1 2024 within the Inbox folder. System folder names like `"Inbox"`, `"Sent Items"`, `"Drafts"` can be used directly in `directories` — for custom folders, use the ID from `list_folders`.

**Usage notes:**

- Call `list_folders` first to obtain folder IDs for the `directories` filter (not needed for well-known system folders).
- Call `list_categories` first to obtain valid category names for the `categories` filter.
- Pass a result's `id` to `open_email_by_id` to retrieve the full email body.
- If `syncWarning` is present, the full sync is still running — results are partial.

---

### `open_email_by_id`

Retrieve the full content of an email by its ID returned from `search_emails`.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | The content ID returned by `search_emails` |

**Return shape:**

```typescript
{
  success: boolean;
  status?: string;
  message?: string;
  emailData?: {
    id: string;
    title: string | null;
    metadata: unknown | null;
    chunks?: Array<{
      id: string;
      startPage: number | null;
      endPage: number | null;
      order: number | null;
      text: string;
    }>;
  };
}
```

**Usage notes:**

- Use this to read the full body of an email after finding it via `search_emails`. The `id` in `search_emails` results is the Unique content ID, not the Microsoft message ID.

---

## Draft Creation

### `create_draft_email`

Create a draft email in the connected Outlook mailbox. The draft is saved to the Drafts folder but **not sent** — the user must open it in Outlook and send manually.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | Yes | Subject line |
| `content` | string | Yes | Email body. Must match the format declared in `contentType` |
| `contentType` | `"html"` \| `"text"` | Yes | Body format — `"html"` for rich HTML, `"text"` for plain text |
| `toRecipients` | array | Yes | Primary recipients |
| `toRecipients[].email` | string (email) | Yes | Recipient email address |
| `toRecipients[].name` | string | No | Recipient display name |
| `ccRecipients` | array | No | CC recipients (same shape as `toRecipients`) |
| `attachments` | array | No | Files to attach |
| `attachments[].fileName` | string | Yes | File name including extension (e.g. `"report.pdf"`) |
| `attachments[].data` | string | Yes | File content URI. Two schemes supported (see below) |

**Attachment data URI schemes:**

| Scheme | Format | Description |
|--------|--------|-------------|
| Unique KB | `unique://content/{contentId}` | File from the Unique knowledge base |
| Inline base64 | `data:[mediatype];base64,<data>` | Base64-encoded content with explicit MIME type |

!!! warning "Attachment scheme availability"
    The `unique://content/{contentId}` scheme only works when `UNIQUE_SERVICE_AUTH_MODE=cluster_local`. In external auth mode the Unique ingestion service cannot resolve internal content URIs — use the `data:[mediatype];base64,<data>` scheme instead.

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  draftId?: string;             // Microsoft message ID
  webLink?: string;             // link to open draft in Outlook
  attachmentsFailed?: Array<{
    fileName: string;
    reason: string;
  }>;
}
```

**Usage notes:**

- Use `lookup_contacts` to resolve recipient email addresses before calling this tool.
- If attachments partially fail, the draft is still created and `draftId` is returned alongside the `attachmentsFailed` list.
- The `webLink` in the response opens the draft directly in Outlook Web.

---

## Contact Lookup

### `lookup_contacts`

Search for contacts by name across the Microsoft People API and the connected inbox. Use this to resolve recipient addresses before creating a draft.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string (min 2 chars) | Yes | Name or partial name to search for |

**Return shape:**

```typescript
{
  contacts: Array<{
    name: string;
    email: string;
    source: "people_api" | "inbox";
    similarityScore: number;
  }>;
  message?: string;
}
```

**Usage notes:**

- Results come from two sources: the Microsoft People API (colleagues, frequent contacts) and emails found in the synced inbox.
- `similarityScore` ranks results by name similarity — use this to surface the best match.

---

## Mailbox Utilities

These tools return metadata needed to build filters for `search_emails`. They do not manage or modify mailbox data.

### `list_categories`

List all Outlook mail categories available for the user.

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  status?: string;
  categories?: string[];        // category display names
  count?: number;
}
```

**Usage notes:**

- Category names returned here can be passed to the `categories` filter in `search_emails`.

---

### `list_folders`

List all Outlook mail folders in a hierarchical tree.

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  status?: string;
  folders?: Array<{
    id: string;
    displayName: string;
    children: Array<...>;       // recursive, same shape
  }>;
}
```

**Usage notes:**

- Folder `id` values can be passed to the `directories` filter in `search_emails` to narrow results to a specific folder.
- The folder tree is synced from Microsoft Graph and reflects the user's current mailbox structure.

---

## Subscription Management

### `verify_inbox_connection`

Check the status of the inbox connection and Microsoft Graph webhook subscription.

**Input parameters:** None

**Return shape:**

```typescript
{
  status: "active" | "expiring_soon" | "expired" | "not_configured";
  message: string;
  subscription: {
    id: string;
    expiresAt: string;
    minutesUntilExpiration: number;
    createdAt: string;
    updatedAt: string;
  } | null;
}
```

| Status | Meaning | Action |
|--------|---------|--------|
| `active` | Subscription is valid | None required |
| `expiring_soon` | Expires within 15 minutes | Renewal is automatic; no action needed |
| `expired` | Subscription has lapsed | Call `reconnect_inbox` |
| `not_configured` | No subscription exists | Call `reconnect_inbox` |

---

### `reconnect_inbox`

Re-establish the Microsoft Outlook inbox subscription when expired or not configured.

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  subscription: {
    id: string;
    expiresAt: string;
    minutesUntilExpiration: number;
    status: "created" | "already_active" | "expiring_soon";
  } | null;
}
```

**Usage notes:**

- Safe to call even if a subscription already exists — it will return `already_active` without creating a duplicate.
- Also triggers a new full sync if one has not been run.

---

### `remove_inbox_connection`

Remove the inbox connection and cease ingesting emails. Deletes the Microsoft Graph webhook subscription.

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  subscription: {
    id: string;
    status: "removed" | "not_found";
  } | null;
}
```

**Usage notes:**

- After removal, no new emails will be ingested. Because the root scope is removed, all previously ingested email content for that user is also removed from the Unique knowledge base.
- To resume ingestion, call `reconnect_inbox`.

---

## Sync Monitoring

### `sync_progress`

Check the current state of the full email sync and live catch-up pipeline. Call this after a `syncWarning` is returned by `search_emails`, or to monitor initial sync progress after connecting.

**Input parameters:** None

**Return shape:**

```typescript
{
  state: "error" | "running" | "finished";
  message: string;
  userEmail: string;
  syncStats?: {
    fullSyncState: "ready" | "running" | "paused" | "waiting-for-ingestion" | "failed";
    liveCatchUpState: "ready" | "running" | "failed";
    runAt: string | null;           // last completion time
    startedAt: string | null;       // last start time
    expectedTotal: number | null;   // total emails at sync start
    skippedMessages: number;        // filtered out by inbox filters
    scheduledForIngestion: number;  // successfully uploaded
    failedToUploadForIngestion: number;
    filters: {
      ignoredBefore: string | null;
      ignoredSenders: string[];
      ignoredContents: string[];
    };
    dateWindow: {
      newestCreatedDateTime: string | null;
      oldestCreatedDateTime: string | null;
      newestLastModifiedDateTime: string | null;
    };
  } | null;
  ingestionStats?: {
    failed: number;
    finished: number;
    inProgress: number;
  } | { state: "error" } | null;
}
```

**Usage notes:**

- `state: "running"` means the full sync is actively fetching and uploading. Search results will be partial until `state: "finished"`.
- `scheduledForIngestion` counts emails uploaded to Unique; `ingestionStats.finished` counts those confirmed processed by the knowledge base.
- `failedToUploadForIngestion` emails were skipped after retries — check operator logs for details.

---

## Debug-Mode Tools

The following four tools are only available when `MCP_DEBUG_MODE=enabled` is set in the server configuration. They are intended for operators diagnosing sync issues, not for end users.

### `run_full_sync`

Trigger a full re-sync of the Outlook mailbox into the knowledge base. Skips if a sync was run recently.

**Input parameters:** None

**Return shape:** `{ success: boolean; message: string }`

**Usage notes:** Use `sync_progress` to monitor progress after triggering.

---

### `pause_full_sync`

Pause an in-progress full sync. The current batch finishes before the sync stops.

**Input parameters:** None

**Return shape:** `{ success: boolean; message: string }`

**Usage notes:** Use `resume_full_sync` to continue from where the sync paused.

---

### `resume_full_sync`

Resume a paused full sync from the point it was paused.

**Input parameters:** None

**Return shape:** `{ success: boolean; message: string }`

---

### `restart_full_sync`

Restart the full sync from scratch, discarding all previous progress.

**Input parameters:** None

**Return shape:** `{ success: boolean; message: string; version?: string }`

**Usage notes:** This is destructive — all sync progress counters and the next-page cursor are reset. Use only when recovering from a corrupted sync state.

---

## Related Documentation

- [Full Sync](./full-sync.md) - Full sync mechanics, states, and filters
- [Live Catch-Up](./live-catchup.md) - Webhook-driven real-time ingestion
- [Flows](./flows.md) - Sequence diagrams for OAuth, sync, and draft creation flows
- [Permissions](./permissions.md) - Microsoft Graph permissions required by these tools
