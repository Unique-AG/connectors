<!-- confluence-page-id: 2061238285 -->
<!-- confluence-space-key: PUBDOC -->

The Outlook Semantic MCP Server exposes tools whose availability depends on the deployment mode (`MCP_BACKEND`) and debug settings.

!!! warning "Mode A (`microsoft_graph_and_unique_api`) only tools"
    `verify_inbox_connection`, `reconnect_inbox`, `delete_inbox_data`, and `sync_progress` are **only available when `MCP_BACKEND=microsoft_graph_and_unique_api`**. They are not registered in `microsoft_graph` mode.

!!! warning "Debug-Mode Tools"
    `run_full_sync`, `pause_full_sync`, `resume_full_sync`, and `restart_full_sync` are **only available when `MCP_BACKEND=microsoft_graph_and_unique_api` AND `MCP_DEBUG_MODE=enabled`**. They do not appear for standard deployments or in `microsoft_graph` mode. **Note:** Debug mode exposes these tools to **all** connected MCP users, not just operators. Do not leave enabled in production.

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
| [`list_calendars`](#list_calendars) | Calendar | No | Both, `CALENDAR_INTEGRATION` |
| [`search_calendar_events`](#search_calendar_events) | Calendar | No | Both, `CALENDAR_INTEGRATION` |
| [`check_availability`](#check_availability) | Calendar | No | Both, `CALENDAR_INTEGRATION` |
| [`suggest_meeting_times`](#suggest_meeting_times) | Calendar | No | Both, `CALENDAR_INTEGRATION` |
| [`respond_to_invite`](#respond_to_invite) | Calendar | Yes | Both, `CALENDAR_INTEGRATION` |
| [`create_event`](#create_event) | Calendar | Yes | Both, `CALENDAR_INTEGRATION` |
| [`update_event`](#update_event) | Calendar | Yes | Both, `CALENDAR_INTEGRATION` |
| [`cancel_event`](#cancel_event) | Calendar | Yes | Both, `CALENDAR_INTEGRATION` |

!!! warning "Calendar tools"
    The eight calendar tools are registered only when `CALENDAR_INTEGRATION=enabled`. They query Microsoft Graph live (no calendar ingest). Writes notify attendees immediately after in-chat confirmation. See [Calendar](#Calendar).

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
| `respond_to_invite` | Notifies the organizer of accept / tentative / decline via Microsoft Graph |
| `create_event` | Creates an event on the chosen mailbox calendar; invitations are sent immediately |
| `update_event` | Patches an existing event; attendees are notified immediately |
| `cancel_event` | Cancels an event and notifies attendees (not a silent delete) |

---

## Email Search

### `search_emails`

Search emails and return matched passages. The tool behaviour and input schema differ by deployment mode.

**Available in:** Both modes

---

#### Mode A: `microsoft_graph_and_unique_api`

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

#### Mode B: `microsoft_graph`

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
- Folder filtering via `directories` is only effective in Mode A (`microsoft_graph_and_unique_api`). In Mode B, the Microsoft Graph Search API does not support folder-scoped filtering — the `directories` condition is ignored.
- Well-known system folder names (`"Inbox"`, `"Sent Items"`, `"Drafts"`, etc.) can be used directly in `search_emails` without calling this tool first.
- When `DELEGATED_ACCESS_SCAN` is enabled, the `mailboxes` array includes delegated mailboxes alongside the user's own mailbox. The `isOwn` field is `true` for the user's primary mailbox and `false` for delegated ones. Folder IDs from delegated mailboxes can be passed to the `directories` condition in `search_emails` to narrow results to a specific folder in a delegated mailbox (folder filtering via `directories` is only effective in Mode A).

---

## Subscription Management

!!! note "Mode A (`microsoft_graph_and_unique_api`) only"
    `verify_inbox_connection`, `reconnect_inbox`, and `delete_inbox_data` are only available when `MCP_BACKEND=microsoft_graph_and_unique_api`. These tools are not registered in `microsoft_graph` mode because no webhook subscriptions are created.

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

!!! note "Mode A (`microsoft_graph_and_unique_api`) only"
    `sync_progress` is only available when `MCP_BACKEND=microsoft_graph_and_unique_api`. There is no sync pipeline in `microsoft_graph` mode.

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

!!! note "Mode A (`microsoft_graph_and_unique_api`) only"
    These tools are only available when `MCP_BACKEND=microsoft_graph_and_unique_api` AND `MCP_DEBUG_MODE=enabled`.

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

## Calendar

**Available in:** Both modes, only when `CALENDAR_INTEGRATION=enabled`. Live Graph query-through — no calendar ingest, webhooks, or calendar tables. Shared-mailbox **profiles** never call these tools.

Write tools (`respond_to_invite`, `create_event`, `update_event`, `cancel_event`) notify other people immediately after in-chat confirmation. There is no draft state. Confirmation is Accept / Decline on the prompt — there is no extra checkbox. For a recurring `update_event` or `cancel_event`, the prompt also asks this occurrence or the entire series. `cancel_event` notifies attendees; it is not a silent delete.

If a calendar tool returns `consentRequired: true`, Graph denied calendar permission on the signed-in user's own mailbox (usually missing `Calendars.ReadWrite.Shared`). Ask the user to reconnect Outlook so they run Microsoft OAuth again. Do not call `reconnect_inbox` — that only renews the mail webhook. Do not send them to `/auth/authorize` — that is the MCP OAuth start URL for clients, not a user reconnect. See [Configuration — CALENDAR_INTEGRATION](../operator/configuration.md#CALENDAR_INTEGRATION) and [Permissions](./permissions.md).

Do not display `calendarRef`, `eventRef`, `calendarId`, `eventId`, or `mailbox`. Pass `calendarRef` (from `list_calendars`) and `eventRef` (from `search_calendar_events`) through unchanged — never assemble one from parts.

### ID namespaces

Graph calendar and event IDs belong to **one mailbox**. An ID read from `/users/{a}/calendars` returns `404 ErrorItemNotFound` under `/users/{b}`, in both directions.

So the mailbox is **provenance**, not a property of the calendar: it is whichever list the ID came out of. `list_calendars` reads `/users/{caller}/calendars` and records the caller as `mailbox`. Search and writes always use `/users/{email}/…` (never `/me/calendars`).

| How the user reaches the calendar | Listed from | `mailbox` | IDs are valid on |
| --- | --- | --- | --- |
| Their own calendars | `/users/{caller}/calendars` | caller SMTP | `/users/{caller}/calendars/{calendarId}/…` |
| A calendar somebody shared with them (they accepted the invitation) | `/users/{caller}/calendars` | **caller SMTP** | `/users/{caller}/calendars/{calendarId}/…` |

A shared calendar is owned by somebody else but **stored in the caller's mailbox**, so `mailbox` is the caller while `ownerEmail` is the owner. Those two fields answer different questions and must not be conflated:

- `mailbox` — routing. Where the ID resolves. Never displayed.
- `ownerEmail` / `ownerName` — display and filtering. Who it belongs to.

Never infer `mailbox` from the payload. Graph sets `isTallyingResponses: true` on a shared calendar, and treating that as "this is the owner's primary calendar" routes shared calendars to a 404.

### `list_calendars`

List Outlook calendars the signed-in user can access: their own, and calendars shared with them that they accepted.

**Input parameters:** None

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  calendars?: Array<{
    calendarRef: { calendarId: string; mailbox: string }; // pass through unchanged; never display
    name: string;
    ownerEmail: string | null;  // SMTP of the owner; on isOwn true this is the signed-in user
    ownerName: string | null;
    isOwn: boolean;             // false when the calendar is shared with the user
    isDefaultCalendar: boolean; // true for the mailbox's primary calendar
    canEdit: boolean;
    canViewPrivateItems: boolean;
  }>;
  consentRequired?: true;
}
```

**Usage notes:**

- Primary calendars are listed first. Holiday and birthday calendars appear too — skip those by name.
- Shared calendars have `isOwn: false` and `isDefaultCalendar: false` and still hold meetings. Do not skip every `isDefaultCalendar: false` calendar.
- For meetings between people, pass every `isDefaultCalendar: true` `calendarRef` and every `isOwn: false` `calendarRef` to `search_calendar_events`.
- `ownerEmail` on a calendar with `isOwn: true` is the signed-in user SMTP — use it in `check_availability` and `suggest_meeting_times` `attendees` when they want to attend.

---

### `search_calendar_events`

Search events in a time window across calendars returned by `list_calendars`. Each result includes the full plain-text body; there is no second tool to open an event.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `calendars` | array of `calendarRef` (1–50) | Yes | From `list_calendars`. Pass each `calendarRef` through unchanged. Never assemble one from a mailbox address. |
| `dateRange` | object | Yes | Prefer `rangeType: "relative"` with a documented range. Absolute `startDateTime` / `endDateTime` must include a timezone offset (`Z` or `±HH:MM`). |
| `attendees` | email[] (max 10) | No | Every listed SMTP must be on the event (organizer or attendee). Exact whole-address match — resolve a name with `lookup_contacts` first. |
| `subject` | `{ startsWith }` or `{ contains }` | No | Exactly one form. Prefer `contains` unless you know how the title begins. |
| `categories` | string[] (max 10) | No | Every listed Outlook category must be on the event. Omit rather than guess. |

Relative `dateRange.range` values: `today`, `tomorrow`, `yesterday`, `thisWeek`, `nextWeek`, `lastWeek`, `thisMonth`, `nextMonth`, `lastMonth`, `thisYear`, `nextYear`, `lastYear`, `next7Days`, `next30Days`, `next90Days`, `past7Days`, `past30Days`. Weeks start Monday. `today` is the whole mailbox-local day (including meetings that already happened).

**Which filters Graph evaluates**

Results are capped. Where a filter runs relative to that cap decides what an empty result proves.

| Filter | Where | Why |
|---|---|---|
| `subject.startsWith` / `subject.contains` | Graph | Narrows **before** the cap. Everything returned is a real match; `searchNotes` reports when more exist. |
| `attendees` | in-process | Graph cannot filter into attendee email addresses. Applied **after** the cap, on what Graph already returned. |
| `categories` | in-process | Graph cannot express the AND of several categories. Applied **after** the cap. |
| window | Graph | Required `startDateTime` / `endDateTime`. |

`attendees` and `categories` are AND filters: every named person or category has to be on the event. An empty result from those filters does not prove the meeting does not exist — matching events may sit outside the fetched set. When `searchNotes` reports a cap, say the answer may be incomplete and offer a narrower window.

**Return shape:**

```typescript
{
  success: boolean;
  message: string;
  events?: Array<{
    subject: string | null;
    body: string;                 // plain-text agenda; may be truncated — see bodyTruncated
    bodyTruncated: boolean;
    start: { dateTime: string; timeZone: string };
    end: { dateTime: string; timeZone: string };
    location: string | null;
    joinUrl: string | null;       // Teams URL when present; never invent one
    attendees: Array<{ name: string | null; email: string | null; response: string | null; type: string | null }>;
    organizerName: string | null;
    organizerEmail: string | null;
    isCancelled: boolean;
    isAllDay: boolean;
    isPrivate: boolean;
    sensitivity: string | null;   // normal, personal, private, confidential
    categories: string[];
    recurrence: string | null;
    seriesMasterId: string | null; // never display
    type: string | null;          // singleInstance, occurrence, exception, seriesMaster
    showAs: string | null;        // free, tentative, busy, oof, workingElsewhere, unknown
    webLink: string | null;       // the only user-facing URL besides joinUrl
    calendarName: string;
    eventRef: { eventId: string; calendarId: string; mailbox: string }; // never display
  }>;
  searchNotes?: string[];         // display after the results
  resolvedWindow?: {
    startDateTime: string;
    endDateTime: string;
    timeZone: string;
    serverCurrentDateTime: string;
    interpretation: string;
  };
  consentRequired?: true;
}
```

**Usage notes:**

- Call `list_calendars` first. Skip holiday and birthday calendars by name.
- If a relative range was used, state `resolvedWindow.interpretation` in the answer.
- Use `webLink` when present; do not invent Outlook URLs.
- Do not use `today` for "when is my next meeting" — that window includes the whole day, so it can return a meeting that already happened. Use `next7Days` (starts now).

---

### `check_availability`

Free/busy for people, distribution lists, or rooms via Graph `getSchedule`. Only `attendees` are checked (at most 20). Include the signed-in user when they want to attend; get their SMTP from `list_calendars` `ownerEmail` on a calendar with `isOwn: true` (prefer `isDefaultCalendar: true`).

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `attendees` | email[] (1–20) | Yes | SMTP addresses to check. |
| `dateRange` | object | Yes | Prefer relative. Must be shorter than 62 days. `thisYear`, `nextYear`, `lastYear`, and `next90Days` are rejected. |
| `intervalMinutes` | integer (5–1440) | No | Length of each availability slot. Default 30. |

**Usage notes:**

- `busyBlocks` are decoded from `availabilityView` (free slots omitted).
- Subject and location on `items` appear only with detail-level permission; private items are redacted.
- Graph error 5006 is returned as a narrow-the-range message (more than 1000 calendar entries in a slot).
- If a relative range was used, state `resolvedWindow.interpretation`.

---

### `suggest_meeting_times`

Ranked free slots via Graph `findMeetingTimes`. Always runs as the signed-in user (the organizer). Include them in `attendees` when they want to attend; omit `attendees` for organizer-only.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `attendees` | email[] | No | People who must be free. |
| `dateRange` | object | Yes | Future window. Prefer relative (`today`, `tomorrow`, `thisWeek`, `nextWeek`, `next7Days`). Must be shorter than 62 days. Past-only ranges are rejected. |
| `durationMinutes` | integer (5–1440) | No | Default 30. |
| `maxCandidates` | integer (1–20) | No | Default 5. |
| `activityDomain` | `"work"` \| `"personal"` \| `"unrestricted"` | No | Default `work` (signed-in user working hours). |
| `isOrganizerOptional` | boolean | No | Default false. |
| `minimumAttendeePercentage` | number (0–100) | No | Default 50. |

**Usage notes:**

- If `emptySuggestionsReason` is present, explain it and suggest widening the window. Do not invent slots.

---

### `respond_to_invite`

Accept, tentatively accept, or decline an invitation. Pass `eventRef` from `search_calendar_events` unchanged. The user must confirm before the organizer is notified.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `eventRef` | object | Yes | From `search_calendar_events`. Never display it. |
| `response` | `"accept"` \| `"tentativelyAccept"` \| `"decline"` | Yes | Sent immediately after confirmation. |
| `comment` | string | No | Optional note included with the response. |

---

### `create_event`

Create an event. There is no draft — if attendees are included, invitations are sent immediately after the user confirms.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `subject` | string | Yes | Event title. |
| `startDateTime` | string | Yes | Inclusive start with timezone offset, e.g. `2026-08-26T09:00:00+02:00`. |
| `endDateTime` | string | Yes | Exclusive end with timezone offset. Must be after `startDateTime`. |
| `attendees` | email[] (max 20) | No | Required attendees. Omit for an appointment with no invitations. |
| `location` | string | No | Location display name. |
| `body` | string | No | Agenda as HTML, sent to Outlook unchanged. Use `<p>`, `<br>`, `<strong>`, `<em>`, lists, and links. Fragment only — no document wrappers and no Teams join section. |
| `isOnlineMeeting` | boolean | No | If true, create a Teams meeting and return a join URL. |
| `calendarRef` | object | No | From `list_calendars`. Omit to use the signed-in user default calendar. |
| `transactionId` | string (max 32) | No | Idempotency key. Reuse the same value if this create is retried. |

**Usage notes:**

- All-day events are not supported yet.
- The confirmation names the destination calendar by owner, not mailbox. The user confirms with Accept / Decline on the prompt.
- `canEdit` must be true on the chosen calendar.
- `body` is HTML sent to Graph unchanged (`contentType: HTML`). Do not write Markdown. Graph appends the Teams join HTML when `isOnlineMeeting` is true.

---

### `update_event`

Change an existing event. Pass `eventRef` from `search_calendar_events` unchanged. Attendees are notified immediately after confirmation. For a recurring meeting the user chooses this occurrence or the whole series.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `eventRef` | object | Yes | From `search_calendar_events`. |
| `subject` | string | No | Replacement title. |
| `startDateTime` / `endDateTime` | string | No | Replacement times with timezone offset. |
| `attendees` | email[] (max 20) | No | Replaces the entire attendee list. An empty list removes every attendee. |
| `location` | string | No | Replacement location. |
| `body` | string | No | Replacement agenda as HTML, sent to Outlook unchanged. Fragment only. Do not include the Teams join section. Omit to leave the body unchanged. |
| `isOnlineMeeting` | `true` | No | Add a Teams meeting. Omit to leave unchanged. |

At least one field besides `eventRef` must be set.

A Teams meeting body is an HTML document Graph already owns. Inside `<body>` the user agenda comes first, then Microsoft's insert: a gray underscore rule, a `div.me-email-text` block (Join Microsoft Teams Meeting link, dial-in, conference ID, Local numbers / Reset PIN / Learn more / Meeting options), and a closing underscore rule. Updating `body` writes the agent's HTML into the user-agenda region only; the Microsoft block is not rewritten, and the agent's HTML is not converted or escaped.

---

### `cancel_event`

Cancel an event and notify attendees. This is not a silent delete. Only the organizer can cancel. Pass `eventRef` unchanged. For a recurring meeting the user chooses this occurrence or the whole series.

**Input parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `eventRef` | object | Yes | From `search_calendar_events`. |
| `comment` | string | No | Optional note included on the cancellation. |

---

### Example prompts

These are user prompts. The assistant should use the named tools and never show internal IDs.

#### What meetings do I have next week?

> What meetings do I have next week?

Use `list_calendars`, then `search_calendar_events` with `dateRange.rangeType: relative` and `range: nextWeek`. Weeks start Monday. State `resolvedWindow.interpretation` in the answer. Show subject, start/end (with timezone), attendees and their response, location and/or Teams `joinUrl`, and the agenda from `body`. Use `webLink` when present; do not invent Outlook URLs.

#### When is my next meeting with XY?

> When is my next meeting with Alex Rivera?

Resolve the name with `lookup_contacts` first. Then `search_calendar_events` with `dateRange.rangeType: relative`, `range: next7Days` (starts now), and `attendees: ['alex.rivera@…']`. Answer with the soonest hit: when, where / join URL, and who else is on it. Widen the range only if that window is empty. Do not use `today` for this question.

#### Create a meeting invite for XY

> Create a 30-minute invite for Alex Rivera tomorrow at 10:00, subject Sync, Teams meeting.

1. Optional: `suggest_meeting_times` or `check_availability` if the time is not already agreed.
2. `create_event` with offset-bearing `startDateTime` / `endDateTime`, `attendees: ["alex@example.com"]`, `isOnlineMeeting: true` if they asked for Teams.
3. The user must confirm. Invitations are sent immediately; there is no draft. If the create is retried, reuse `transactionId`.

Shared-calendar create: `list_calendars`, then pass that `calendarRef` unchanged. The confirmation names the destination by owner, not mailbox.

---

## Related Documentation

- [Full Sync](./flows.md#Full-Sync:-Historical-Email-Ingestion) - Full sync mechanics and states
- [Live Catch-Up](./flows.md#Live-Catch-Up:-Webhook-Driven-Email-Ingestion) - Webhook-driven real-time ingestion
- [Flows](./flows.md) - Sequence diagrams for OAuth, sync, and draft creation flows
- [Permissions](./permissions.md) - Microsoft Graph permissions required by these tools
- [Features — Calendar](./features.md#Calendar) - What is supported, what is not
- [Configuration — CALENDAR_INTEGRATION](../operator/configuration.md#CALENDAR_INTEGRATION) - Operator enablement and re-consent
