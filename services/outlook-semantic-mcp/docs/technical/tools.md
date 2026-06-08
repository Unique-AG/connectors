<!-- confluence-page-id: 2061238285 -->
<!-- confluence-space-key: PUBDOC -->

# Outlook Semantic MCP - Tools

The Outlook Semantic MCP Server exposes tools whose availability depends on the deployment mode (`MCP_BACKEND`) and debug settings.

!!! warning "Mode A (`MicrosoftGraphAndUniqueApi`) only tools"
    `verify_inbox_connection`, `reconnect_inbox`, `delete_inbox_data`, and `sync_progress` are **only available when `MCP_BACKEND=MicrosoftGraphAndUniqueApi`**. They are not registered in `MicrosoftGraph` mode.

!!! warning "Debug-Mode Tools"
    `run_full_sync`, `pause_full_sync`, `resume_full_sync`, and `restart_full_sync` are **only available when `MCP_BACKEND=MicrosoftGraphAndUniqueApi` AND `MCP_DEBUG_MODE=enabled`**. They do not appear for standard deployments or in `MicrosoftGraph` mode. **Note:** Debug mode exposes these tools to **all** connected MCP users, not just operators. Do not leave enabled in production.

## Tool Overview

| Tool | Category | Mutating | Mode |
|------|----------|----------|------|
| [`search_emails`](#search_emails) | Email Search | No | Both |
| [`open_email`](#open_email) | Email Search | No | Both |
| [`create_draft_email`](#create_draft_email) | Draft Creation | Yes | Both |
| [`lookup_contacts`](#lookup_contacts) | Contact Lookup | No | Both |
| [`list_categories`](#list_categories) | Mailbox Utilities | No | Both |
| [`list_mailboxes_and_directories`](#list_mailboxes_and_directories) | Mailbox Utilities | Yes | Both |
| [`verify_inbox_connection`](#verify_inbox_connection) | Subscription Management | No | Mode A only |
| [`reconnect_inbox`](#reconnect_inbox) | Subscription Management | Yes | Mode A only |
| [`delete_inbox_data`](#delete_inbox_data) | Subscription Management | Yes | Mode A only |
| [`sync_progress`](#sync_progress) | Sync Monitoring | No | Mode A only |
| [`run_full_sync`](#run_full_sync) | Full Sync Control (debug only) | Yes | Mode A only |
| [`pause_full_sync`](#pause_full_sync) | Full Sync Control (debug only) | Yes | Mode A only |
| [`resume_full_sync`](#resume_full_sync) | Full Sync Control (debug only) | Yes | Mode A only |
| [`restart_full_sync`](#restart_full_sync) | Full Sync Control (debug only) | Yes | Mode A only |

**Mutating** means the tool writes data to at least one of the following:

- **Outlook mailbox** — creates or modifies data in Microsoft Graph (e.g. a draft email or a webhook subscription)
- **Internal database** — persists or removes state managed by this server (e.g. subscription records, sync state, folder cache)
- **Unique knowledge base** — indexes or removes email content from the knowledge base used for search

| Tool | What it mutates |
|------|----------------|
| `create_draft_email` | Creates a draft message in the user's Outlook mailbox via Microsoft Graph |
| `list_mailboxes_and_directories` | Refreshes the folder cache in the internal database by re-fetching the folder tree from Microsoft Graph |
| `reconnect_inbox` | Creates or renews the Microsoft Graph webhook subscription and writes the subscription record to the internal database |
| `delete_inbox_data` | Cancels the Microsoft Graph webhook subscription and deletes the subscription record, folder cache, root scope, and all ingested email content from the Unique knowledge base |
| `run_full_sync` | Triggers ingestion of all mailbox emails into the Unique knowledge base and updates sync state in the internal database |
| `pause_full_sync` | Updates the sync state to `paused` in the internal database |
| `resume_full_sync` | Updates the sync state to resume ingestion in the internal database |
| `restart_full_sync` | Resets sync state in the internal database and re-triggers full ingestion into the Unique knowledge base |

---

## Email Search

### `search_emails`

Search emails and return matched passages. The tool behaviour and input schema differ by deployment mode.

**Available in:** Both modes

---

#### Mode A: `MicrosoftGraphAndUniqueApi`

Runs two searches in parallel — semantic search against the Unique knowledge base and a KQL keyword search against Microsoft Graph — then merges and deduplicates the results. Both query arrays are required and must address the same user question.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `uniqueSemanticSearchQueries` | array (1–10) | Yes | Semantic searches. Compose 2–4 parallel entries that approach the question from different angles. |
| `msGraphKeywordSearchQueries` | array (1–10) | Yes | KQL keyword searches addressing the same question. |

Each entry in `uniqueSemanticSearchQueries`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `search` | string | Yes | Natural-language search query |
| `mailbox` | email | No | Scope to one mailbox. When omitted all accessible mailboxes are searched. |
| `conditions` | array | No | Structured filters. Multiple condition objects are OR-combined; fields within one object are AND-combined. |
| `limit` | integer (100–200) | No | Maximum results for this query. Default: 100. Use 200 for broad queries. |

Each entry in `msGraphKeywordSearchQueries`:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `kqlQuery` | string | Yes | KQL query string. See [KQL reference](#KQL-reference) below. |
| `mailbox` | email | No | Scope to one mailbox. |
| `limit` | integer (1–100) | No | Maximum results for this query. Default: 100. |

Each object in `conditions` (applies to `uniqueSemanticSearchQueries` entries only) may include:

| Field | Type | Description |
|-------|------|-------------|
| `dateFrom` | `{ value: string, operator }` | ISO 8601 UTC — emails received on or after this date |
| `dateTo` | `{ value: string, operator }` | ISO 8601 UTC — emails received on or before this date |
| `fromSenders` | `{ value: string, operator }` or `{ value: string[], operator: "in" \| "notIn" \| "containsAny" }` | Filter by sender. Use `contains` for domain matching (e.g. `"google.com"`), `containsAny` for a list. |
| `toRecipients` | `{ value: string, operator }` or array form | Filter by To recipient |
| `ccRecipients` | `{ value: string, operator }` or array form | Filter by CC recipient |
| `directories` | `{ value: string[], operator: "in" \| "notIn" }` | Folder IDs from `list_mailboxes_and_directories`, or well-known names: `"Inbox"`, `"Sent Items"`, `"Drafts"`, `"Archive"`, `"Outbox"`, `"Clutter"`, `"Conversation History"`. Note: `"Deleted Items"`, `"Junk Email"`, and `"Recoverable Items Deletions"` are not synchronized and return no results. |
| `hasAttachments` | `{ value: "true" \| "false", operator }` | Filter by attachment presence. Value is a string, not a boolean. |
| `categories` | `{ value: string, operator }` or array form | Category labels from `list_categories` |

**Available operators:**

- Singular: `equals`, `notEquals`, `greaterThan`, `greaterThanOrEqual`, `lessThan`, `lessThanOrEqual`, `contains`, `notContains`, `isNull`, `isNotNull`, `isEmpty`, `isNotEmpty`
- Array: `in`, `notIn`, `containsAny` (email fields only — expands to OR of `contains` filters)

**Example (Mode A):**

```json
{
  "uniqueSemanticSearchQueries": [
    {
      "search": "quarterly report from Alice",
      "conditions": [
        {
          "fromSenders": { "value": "alice@example.com", "operator": "equals" },
          "dateFrom": { "value": "2024-01-01T00:00:00Z", "operator": "greaterThanOrEqual" }
        }
      ],
      "limit": 100
    },
    {
      "search": "Q1 budget summary",
      "conditions": [
        {
          "fromSenders": { "value": "alice@example.com", "operator": "equals" }
        }
      ],
      "limit": 100
    }
  ],
  "msGraphKeywordSearchQueries": [
    {
      "kqlQuery": "from:alice@example.com subject:\"quarterly report\" received>=2024-01-01",
      "limit": 100
    }
  ]
}
```

---

#### Mode B: `MicrosoftGraph`

Calls the Microsoft Graph Search API directly with KQL queries. No semantic search is performed. Only `msGraphKeywordSearchQueries` is accepted.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `msGraphKeywordSearchQueries` | array (1–10) | Yes | KQL keyword searches. |

Each entry uses the same `kqlQuery`, `mailbox`, and `limit` fields as described in Mode A above.

**Note:** Folder filtering via `directories` conditions is not supported in Mode B. The Microsoft Graph Search API does not expose a folder-scoped KQL predicate.

**Example (Mode B):**

```json
{
  "msGraphKeywordSearchQueries": [
    {
      "kqlQuery": "from:alice@example.com subject:\"quarterly report\" received>=2024-01-01",
      "limit": 100
    }
  ]
}
```

---

#### KQL reference

Supported KQL property filters for `kqlQuery`:

| Filter | Example | Notes |
|--------|---------|-------|
| `from:<email>` | `from:alice@example.com` | Sender SMTP, display name, or domain |
| `to:<email>` | `to:bob@example.com` | To recipient |
| `cc:<email>` | `cc:alice@example.com` | CC recipient |
| `participants:<email>` | `participants:alice@example.com` | Any of from/to/cc/bcc |
| `subject:<words>` | `subject:"budget report"` | Words in subject |
| `body:<words>` | `body:proposal` | Words in body |
| `received>=YYYY-MM-DD` | `received>=2024-01-01` | Received on or after |
| `received<=YYYY-MM-DD` | `received<=2024-03-31` | Received on or before |
| `hasAttachment:true\|false` | `hasAttachment:true` | Has attachments |
| `category:"label"` | `category:"Important"` | Outlook category |
| `kind:email` | `kind:email` | Message type |

Syntax rules:
- No space between property and value: `from:alice@example.com` not `from: alice@example.com`
- Boolean operators must be uppercase: `AND`, `OR`, `NOT`
- Suffix wildcards only: `report*`, not `*report`
- Phrases in double quotes: `subject:"quarterly report"`
- Do NOT use `folder:` — it is not supported and causes a request error

---

#### Return shape (both modes)

```typescript
{
  success: boolean;
  message?: string;           // error description when success is false
  status?: string;            // informational subscription/backend status
  syncWarning?: string;       // Mode A only — present when ingestion is incomplete or in error state. Always display to the user before showing results.
  searchNotes?: string;       // informational notes about the search run (e.g. unrecognised folders excluded). Display to the user after results.
  results?: Array<{
    uniqueContentId?: string;     // Unique KB content ID. Present for semantic-backend results only.
    msGraphMessageId?: string;    // Microsoft Graph message ID. Present for Graph-backend results; also present for semantic results when both backends matched the same email.
    backend: "Unique" | "MsGraph"; // which backend returned this result
    folderId: string;              // internal folder ID — do not display to users
    title: string;                 // email subject
    from: string;                  // sender email address
    receivedDateTime?: string | null; // ISO 8601
    text: string;                  // matched passage or excerpt — not the full body
    outlookWebLink: string;        // direct URL to open in Outlook Web — use as link target when non-empty
    sourceMailbox?: string | null; // mailbox this email belongs to
    openEmailParams: {             // pass directly to open_email without modification
      id: string;
      idType: "Unique" | "MsGraph";
      mailbox?: string;
      parentFolderId?: string;
      idIsImmutable?: boolean;
    };
  }>;
}
```

**Usage notes:**

- Pass the `openEmailParams` object from a result directly to `open_email` to retrieve the full email body.
- If `syncWarning` is present (Mode A only), display it to the user and call `sync_progress` to check ingestion status — results may be incomplete.
- If `searchNotes` is present, display it to the user after showing results.
- Folder filtering via `conditions[].directories` is supported in Mode A only.
- Well-known system folder names (`"Inbox"`, `"Sent Items"`, `"Drafts"`) can be used directly in `directories` — no need to call `list_mailboxes_and_directories` for those.
- For custom folders, call `list_mailboxes_and_directories` first to obtain folder IDs.

---

### `open_email`

Retrieve the full content of an email by its ID returned from `search_emails`.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `id` | string | Yes | Email identifier. Use `openEmailParams.id` from a `search_emails` result. |
| `idType` | `"Unique"` \| `"MsGraph"` | Yes | Backend type. Use `openEmailParams.idType` from a `search_emails` result. |
| `mailbox` | email | No | Use `openEmailParams.mailbox` when present. |
| `parentFolderId` | string | No | Use `openEmailParams.parentFolderId` when present. Required when `mailbox` is provided. |
| `idIsImmutable` | boolean | No | Use `openEmailParams.idIsImmutable` when present. |

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
    text: string;              // full email body or the matched chunks depending on which search returned the results
  };
}
```

**Usage notes:**

- Always pass the `openEmailParams` object from a `search_emails` result directly as the tool input — do not construct these parameters manually.
- The `text` field in `emailData` contains the full email body. This is distinct from the `text` field in `search_emails` results, which contains only a matched passage or excerpt.

---

## Draft Creation

### `create_draft_email`

Create a draft email in the connected Outlook mailbox. The draft is saved to the Drafts folder but **not sent** — the user must open it in Outlook and send manually.

Supports two modes selected by `recipientsData.type`:

- **`"draft"`** — fresh draft with explicit recipients (personal or shared mailbox)
- **`"reply"`** — reply-all draft for an existing email; Graph pre-fills all original recipients (personal or shared mailbox)

**Common input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | Email body in Markdown. Paragraphs, bold, italic, lists, links, blockquotes, and inline code are supported. Raw HTML is escaped, not rendered. |
| `mailbox` | string (UPN) | No | Shared mailbox to create the draft in (e.g. `"support@company.com"`). Omit to use the signed-in user's own mailbox. |
| `attachments` | array | No | Files to attach |
| `attachments[].fileName` | string | Yes | File name including extension (e.g. `"report.pdf"`) |
| `attachments[].data` | string | Yes | File content URI. Two schemes supported (see below) |
| `recipientsData` | object | Yes | Discriminated union — see below |

**`recipientsData` — fresh draft (`type: "draft"`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"draft"` | Yes | |
| `subject` | string | Yes | Subject line |
| `toRecipients` | array | Yes | Primary recipients |
| `toRecipients[].email` | string (email) | Yes | Recipient email address |
| `toRecipients[].name` | string | No | Recipient display name |
| `ccRecipients` | array | No | CC recipients (same shape as `toRecipients`) |

**`recipientsData` — reply-all draft (`type: "reply"`):**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `type` | `"reply"` | Yes | |
| `inReplyToMessageId` | string | Yes | `msGraphMessageId` from `search_emails` or `open_email`. Graph pre-fills all original recipients — do not pass `toRecipients` or `ccRecipients`. |

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
  draftId?: string;             // Microsoft message ID (present when success is true)
  webLink?: string;             // link to open draft in Outlook (present when success is true and Graph returned one)
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
- For shared mailbox reply drafts: in Outlook Web the reply appears in the **Drafts** folder rather than inline in the thread — this is expected Outlook Web behaviour. The draft sends correctly regardless. In Outlook desktop the reply appears and sends normally.

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

### `list_mailboxes_and_directories`

List all Outlook mailboxes and their folder trees available to the user.

**Available in:** Both modes

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  status?: string;
  mailboxes?: Array<{
    email: string | null;
    displayName: string | null;
    isOwn: boolean;            // true for the user's own primary mailbox
    folders: Array<{
      id: string;              // pass to directories filter in search_emails
      displayName: string;
      children: Array<...>;    // recursive — same shape
    }>;
  }>;
}
```

**Usage notes:**

- Folder `id` values can be passed to the `directories` filter in `search_emails` to narrow results to a specific folder.
- In Mode A, the folder tree is synced from Microsoft Graph and reflects the user's current mailbox structure. Calling this tool triggers a fresh sync of the folder tree.
- Folder filtering via `directories` is only effective in Mode A (`MicrosoftGraphAndUniqueApi`). In Mode B, the Microsoft Graph Search API does not support folder-scoped filtering — the `directories` condition is ignored.
- Well-known system folder names (`"Inbox"`, `"Sent Items"`, `"Drafts"`, etc.) can be used directly in `search_emails` without calling this tool first.
- When `DELEGATED_ACCESS_SCAN` is enabled, the `mailboxes` array includes delegated mailboxes alongside the user's own mailbox. The `isOwn` field is `true` for the user's primary mailbox and `false` for delegated ones. Folder IDs from delegated mailboxes can be passed to the `directories` condition in `search_emails` to narrow results to a specific folder in a delegated mailbox (folder filtering via `directories` is only effective in Mode A).

---

## Subscription Management

!!! note "Mode A (`MicrosoftGraphAndUniqueApi`) only"
    `verify_inbox_connection`, `reconnect_inbox`, and `delete_inbox_data` are only available when `MCP_BACKEND=MicrosoftGraphAndUniqueApi`. These tools are not registered in `MicrosoftGraph` mode because no webhook subscriptions are created.

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
- When a new subscription is created (status: `created`), a full sync is triggered automatically. If the subscription is `already_active` or `expiring_soon`, no full sync is triggered.

---

### `delete_inbox_data`

Permanently delete all synced email data from Unique and cancel the Microsoft Graph subscription. This stops future email ingestion and removes all previously ingested email content for your inbox from the Unique knowledge base.

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

- This is a destructive operation: all previously ingested email content for the user is permanently removed from the Unique knowledge base, and no new emails will be ingested.
- To resume ingestion after deletion, call `reconnect_inbox`.

---

## Sync Monitoring

!!! note "Mode A (`MicrosoftGraphAndUniqueApi`) only"
    `sync_progress` is only available when `MCP_BACKEND=MicrosoftGraphAndUniqueApi`. There is no sync pipeline in `MicrosoftGraph` mode.

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
    fullSyncState: "ready" | "running" | "waiting-for-ingestion" | "paused" | "failed";
    liveCatchUpState: "ready" | "running" | "failed";
    runAt: string | null;           // last completion time
    startedAt: string | null;       // last start time
    expectedTotal: number | null;   // total emails at sync start
    skippedMessages: number;        // filtered out by inbox filters
    scheduledForIngestion: number;  // successfully uploaded
    failedToUploadForIngestion: number;
    filters: {
      retentionWindowInDays: number;
      ignoredBefore: string;       // ISO 8601 UTC cutoff — emails before this date are excluded
      ignoredSenders: string[];
      ignoredContents: string[];
    };
    dateWindow: {
      newestReceivedEmailDateTime: string | null;
      oldestReceivedEmailDateTime: string | null;
      newestLastModifiedDateTime: string | null;
    };
  } | null;
  ingestionStats?: {
    failed: number;
    finished: number;
    inProgress: number;
  } | { state: "error" } | null;
  debugData?: {                   // only present when MCP_DEBUG_MODE=enabled
    providerUserId: string;
    userProfileId: string;
    subscriptionId: string;
  } | null;
}
```

**Usage notes:**

- `state: "running"` means the full sync is actively fetching and uploading. Search results will be partial until `state: "finished"`.
- `scheduledForIngestion` counts emails uploaded to Unique; `ingestionStats.finished` counts those confirmed processed by the knowledge base.
- `failedToUploadForIngestion` emails were skipped after retries — check operator logs for details.
- `syncStats.liveCatchUpState: "failed"` indicates the live catch-up pipeline stalled. Recovery is automatic — the `INGESTION_LIVE_CATCHUP_RECOVERY_CRON` scheduler resets it within 5 minutes. No user-callable tool exists for this outside `MCP_DEBUG_MODE`; users should wait and operators can monitor pod logs.

---

## Debug-Mode Tools

The following four tools are only available when `MCP_DEBUG_MODE=enabled` is set in the server configuration. They are intended for operators diagnosing sync issues, not for end users.

!!! note "Mode A (`MicrosoftGraphAndUniqueApi`) only"
    These tools are only available when `MCP_BACKEND=MicrosoftGraphAndUniqueApi` AND `MCP_DEBUG_MODE=enabled`.

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

- [Full Sync](./flows.md#Full-Sync:-Historical-Email-Ingestion) - Full sync mechanics and states
- [Live Catch-Up](./flows.md#Live-Catch-Up:-Webhook-Driven-Email-Ingestion) - Webhook-driven real-time ingestion
- [Flows](./flows.md) - Sequence diagrams for OAuth, sync, and draft creation flows
- [Permissions](./permissions.md) - Microsoft Graph permissions required by these tools
