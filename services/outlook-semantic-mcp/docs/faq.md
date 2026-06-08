<!-- confluence-page-id: 2061107213 -->
<!-- confluence-space-key: PUBDOC -->

# Outlook Semantic MCP - FAQ


## Table of Contents

- [General](#General)
  - [What type of MCP server is this?](#What-type-of-MCP-server-is-this?)
  - [What tools are available?](#What-tools-are-available?)
  - [Do I need to do anything after connecting?](#Do-I-need-to-do-anything-after-connecting?)
- [Data Privacy & Storage](#Data-Privacy-&-Storage)
  - [Does the MCP server store my emails?](#Does-the-MCP-server-store-my-emails?)
  - [Where is my email content stored?](#Where-is-my-email-content-stored?)
  - [What email data is actually ingested into the knowledge base?](#What-email-data-is-actually-ingested-into-the-knowledge-base?)
  - [Who can access my email data once it is ingested?](#Who-can-access-my-email-data-once-it-is-ingested?)
  - [Can an operator with database access read my emails?](#Can-an-operator-with-database-access-read-my-emails?)
  - [What happens to my email data when I disconnect?](#What-happens-to-my-email-data-when-I-disconnect?)
- [Shared Inbox & Delegated Access](#Shared-Inbox-&-Delegated-Access)
  - [How do I set up delegated access?](#How-do-I-set-up-delegated-access?)
  - [Who has access to a shared inbox?](#Who-has-access-to-a-shared-inbox?)
  - [What happens with delegated access?](#What-happens-with-delegated-access?)
  - [When shared inbox access is revoked, are previously ingested emails still accessible?](#When-shared-inbox-access-is-revoked,-are-previously-ingested-emails-still-accessible?)
  - [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)
- [Supported Email Attachment Types](#Supported-Email-Attachment-Types)
- [Tool Usage](#Tool-Usage)
  - [How does search_emails search?](#How-does-search_emails-search?)
  - [How do I filter search results to a specific folder?](#How-do-I-filter-search-results-to-a-specific-folder?)
  - [Can I attach files when creating a draft email?](#Can-I-attach-files-when-creating-a-draft-email?)
  - [Can I create drafts in a shared mailbox?](#Can-I-create-drafts-in-a-shared-mailbox?)
  - [Why does a reply draft in a shared mailbox appear in Drafts instead of in the thread in Outlook Web?](#Why-does-a-reply-draft-in-a-shared-mailbox-appear-in-Drafts-instead-of-in-the-thread-in-Outlook-Web?)
  - [What does reconnect_inbox do?](#What-does-reconnect_inbox-do?)
  - [What does delete_inbox_data do?](#What-does-delete_inbox_data-do?)
- [Sync](#Sync)
  - [What is the difference between full sync and live catch-up?](#What-is-the-difference-between-full-sync-and-live-catch-up?)
  - [How do I check sync progress?](#How-do-I-check-sync-progress?)
  - [Why is my full sync stuck in waiting-for-ingestion?](#Why-is-my-full-sync-stuck-in-waiting-for-ingestion?)
  - [Why is my full sync stuck in running?](#Why-is-my-full-sync-stuck-in-running?)
  - [What happens if full sync is interrupted?](#What-happens-if-full-sync-is-interrupted-(restart,-crash)?)
  - [Why are new emails not appearing in search results?](#Why-are-new-emails-not-appearing-in-search-results?)
  - [What happens to emails sent during full sync?](#What-happens-to-emails-sent-during-full-sync?)
  - [Why are deleted emails still appearing in search results?](#Why-are-deleted-emails-still-appearing-in-search-results?)
- [Authentication & Permissions](#Authentication-&-Permissions)
  - [Do any permissions require admin consent?](#Do-any-permissions-require-admin-consent?)
  - [Why does the server need Mail.ReadWrite if it mostly reads emails?](#Why-does-the-server-need-Mail.ReadWrite-if-it-mostly-reads-emails?)
  - [Why can't I use application permissions instead of delegated?](#Why-can't-I-use-application-permissions-instead-of-delegated?)
  - [Why do I need a client ID and client secret?](#Why-do-I-need-a-client-ID-and-client-secret?)
  - [What is the "login flicker" when users reconnect?](#What-is-the-"login-flicker"-when-users-reconnect?)
  - [What happens when a user's Microsoft refresh token expires?](#What-happens-when-a-user's-Microsoft-refresh-token-expires?)
- [Security](#Security)
  - [How are Microsoft tokens stored?](#How-are-Microsoft-tokens-stored?)
  - [How are MCP tokens stored?](#How-are-MCP-tokens-stored?)
  - [Why does the server use PKCE?](#Why-does-the-server-use-PKCE?)
  - [What happens if a refresh token is stolen?](#What-happens-if-a-refresh-token-is-stolen?)
- [Configuration](#Configuration)
  - [What redirect URI should I configure in Entra ID?](#What-redirect-URI-should-I-configure-in-Entra-ID?)
  - [Why do I need a webhook secret?](#Why-do-I-need-a-webhook-secret?)
  - [What happens if I change the encryption key?](#What-happens-if-I-change-the-encryption-key?)
  - [What happens if I change the webhook secret?](#What-happens-if-I-change-the-webhook-secret?)
  - [What happens if I change the client secret?](#What-happens-if-I-change-the-client-secret?)
  - [What does INGESTION_DEFAULT_MAIL_FILTERS do?](#What-does-INGESTION_DEFAULT_MAIL_FILTERS-do?)
- [Deployment](#Deployment)
  - [Why is RabbitMQ required?](#Why-is-RabbitMQ-required?)
  - [What happens if RabbitMQ is unavailable?](#What-happens-if-RabbitMQ-is-unavailable?)
  - [What happens if PostgreSQL is unavailable?](#What-happens-if-PostgreSQL-is-unavailable?)
  - [Can one deployment serve multiple Microsoft tenants?](#Can-one-deployment-serve-multiple-Microsoft-tenants?)
- [Disaster Recovery](#Disaster-Recovery)
  - [What do I do if a core infrastructure component fails?](#What-do-I-do-if-a-core-infrastructure-component-fails?)
- [Related Documentation](#Related-Documentation)

## General

### What type of MCP server is this?

**Answer:** The Outlook Semantic MCP Server is both an **MCP server** and a **connector**. It exposes 10 tools in `MicrosoftGraphAndUniqueApi` mode (plus 4 debug-mode tools), or 6 tools in `MicrosoftGraph` mode. Once a user connects their account, it automatically syncs their emails into the Unique knowledge base in the background (Mode A only).

**What it does:**

- Automatically ingests the user's email history into the Unique knowledge base after connection, based on the configured filters
- Exposes 10 tools (plus 4 debug-mode tools) for searching emails, managing drafts, listing folders, and monitoring sync status
- Keeps the knowledge base up to date in real time via webhook-driven live catch-up
- Requires no manual setup beyond the initial connection

**What the user sees:**

- An initial OAuth consent screen to connect their Outlook account
- 10 MCP tools available in their AI client immediately after connection (14 with debug mode enabled)
- Search results that may be incomplete while the initial full sync is running (a `syncWarning` is returned by `search_emails`)

The server supports two deployment modes controlled by `MCP_BACKEND`. In the default `MicrosoftGraphAndUniqueApi` mode, it ingests emails into the Unique knowledge base and exposes 10 tools. In `MicrosoftGraph` mode, it skips ingestion entirely and queries Microsoft Graph directly, exposing 6 tools. See [Operator Configuration — Deployment Modes](./operator/configuration.md#Deployment-Modes).

**See also:** [Architecture](./technical/architecture.md) — [Tools](./technical/tools.md)

### What tools are available?

**Answer:** The server exposes 10 user-facing tools:

| Category | Tools |
|----------|-------|
| Email Search | `search_emails`, `open_email` |
| Draft Creation | `create_draft_email` |
| Contact Lookup | `lookup_contacts` |
| Mailbox Utilities | `list_categories`, `list_mailboxes_and_directories` |
| Subscription Management | `verify_inbox_connection`, `reconnect_inbox`, `delete_inbox_data` |
| Sync Monitoring | `sync_progress` |

An additional 4 tools are available only when the server is running in debug mode (`MCP_DEBUG_MODE=enabled`): `run_full_sync`, `pause_full_sync`, `resume_full_sync`, `restart_full_sync`. These are intended for development and troubleshooting and are not exposed in production deployments.

In `MicrosoftGraph` mode, only the first 6 categories are available (Email Search, Draft Creation, Contact Lookup, Mailbox Utilities). Subscription Management and Sync Monitoring tools are not registered.

**See also:** [Tools Reference](./technical/tools.md) — [Debug Mode Tools](./technical/tools.md#Debug-Mode-Tools)

### Do I need to do anything after connecting?

**Answer:** No. After granting consent, the server automatically creates a Microsoft Graph subscription and starts ingesting emails within the operator-configured time frame and filters (see [INGESTION_DEFAULT_MAIL_FILTERS](./operator/configuration.md)). The 10 tools become available immediately (14 with debug mode enabled). Search results may be incomplete while the initial full sync is running.

**Mode B (`MicrosoftGraph`):** No. After granting consent, all 6 tools are available immediately. There is no ingestion pipeline — search results come from live Microsoft Graph queries.


## Data Privacy & Storage

### Does the MCP server store my emails?

**Answer:** No. The Outlook Semantic MCP Server stores **no email content** in its own database. Emails are fetched from Microsoft Graph into memory and forwarded directly to the Unique knowledge base for ingestion. Nothing from the email body, subject, sender, or recipients is written to the MCP server's PostgreSQL database.

The MCP server's PostgreSQL database stores only encrypted OAuth tokens, opaque MCP bearer tokens, sync state, folder metadata, and subscription IDs — no email content. See [Data Classification and Flow](./technical/security.md#Data-Classification-and-Flow) for the full breakdown of what is stored where.

In `MicrosoftGraph` mode, no email content is ever fetched into memory beyond what is needed to return a single search result — no ingestion occurs and nothing is sent to the Unique knowledge base.

### Where is my email content stored?

**Answer:** Email content (subject, body, sender, recipients, and metadata) is stored in the **Unique knowledge base**, not in the MCP server itself. It is ingested there for semantic search and is accessible via the `search_emails` tool.

The Unique knowledge base organizes each user's emails into a dedicated **root scope** (a top-level isolation boundary that logically separates one user's ingested data from another's within the Unique platform).

In `MicrosoftGraph` mode, email content is not stored anywhere — it is queried live from Microsoft Graph per search request and never persisted.

**See also:** [Knowledge Base Data Isolation](./technical/security.md#Knowledge-Base-Data-Isolation)

### Who can access my email data once it is ingested?

**Answer:** (Applies to Mode A — `MicrosoftGraphAndUniqueApi` — only) Access to ingested email data operates at two levels:

**Via the MCP server (tool layer):** The `search_emails` tool returns results from the authenticated user's own email scope. When `DELEGATED_ACCESS_SCAN` is enabled and the user has been granted delegated access to another user's mailbox in Microsoft 365, `search_emails` also returns results from that owner's scope — but only while both users are connected and the access relationship is active. Outside of an explicitly configured delegated access relationship, one user's MCP session cannot access another user's emails.

**Via the Unique platform (platform layer):** Email content stored in the Unique knowledge base is subject to Unique's own access control model. This includes:

- The MCP server's service account, which has write access to the ingestion and scope management APIs used during sync
- Unique platform administrators with API access — email scopes are not surfaced in the Unique Knowledge Base UI, but can be enumerated via the Unique API (e.g. `scopesByCompany`) or accessed directly via the database.

Organizations with strict email privacy requirements should control who has API and database access to the Unique platform.

**See also:** [Knowledge Base Data Isolation](./technical/security.md#Knowledge-Base-Data-Isolation)

### Can an operator with database access read my emails?

**Answer:** No — not from the MCP server's PostgreSQL database. It contains no email content. An operator with direct database access would see only encrypted OAuth tokens, opaque random bearer tokens, sync state, and folder metadata.

Decrypting the stored Microsoft tokens would require the `ENCRYPTION_KEY` value, which should be stored in a Kubernetes Secret and not accessible to most operators.

Access to the email content itself requires access to the Unique knowledge base, which is governed separately by Unique platform policies.

**See also:** [Data Classification and Flow](./technical/security.md#Data-Classification-and-Flow)

### What happens to my email data when I disconnect?

**Answer:** Calling `delete_inbox_data`:

- Deletes the Microsoft Graph subscription (stops future email sync)
- Removes the per-user root scopes from the Unique knowledge base, which also removes all ingested email content for that user
- Clears the inbox configuration and folder sync data from PostgreSQL

In Mode B (`MicrosoftGraph`), there is no inbox data to delete — `delete_inbox_data` is not available in this mode.

**See also:** [Data Removal](./technical/security.md#Data-Removal)

### What email data is actually ingested into the knowledge base?

**Answer:** (Mode A — `MicrosoftGraphAndUniqueApi` — only) The following fields from each email are ingested:

- Subject
- Body (plain text and/or HTML)
- Sender (name and email address)
- To, CC, and BCC recipients
- Received date and time
- Folder Id
- Microsoft-assigned email ID and web link
- Attachments (supported types listed below — note that supported types depend on the Unique knowledge base ingestion pipeline and may change independently of this service)


## Shared Inbox & Delegated Access

> Ingestion never occurs in Mode B (`MicrosoftGraph`) regardless of
> `DELEGATED_ACCESS_SCAN`. The discovery job runs in both modes when enabled.
> In Mode B, only delegates with **full mailbox access** can search delegated
> mailboxes — Microsoft Graph's `$search` parameter requires full mailbox
> access and returns HTTP 403 for any search against a partially-delegated
> mailbox. See [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)

### How do I set up delegated access?

**Answer:** Delegated access setup happens in Microsoft 365, not in the MCP. The MCP supports three configurations: an Exchange admin grants Full Access (Read & Manage), a user shares specific folders via Outlook desktop (with a required root-mailbox visibility step), or a shared inbox is configured as a normal mailbox and connected to the MCP. See [Features — Delegated Access — Setup](./technical/features.md#Setup) for step-by-step instructions and the Outlook root-mailbox visibility gotcha.

---

### Who has access to a shared inbox?

**Answer:** Any user whose Microsoft 365 account has been granted access to
another user's mailbox — either Full Access (Read & Manage) or folder-level
delegation configured via the Exchange admin center. The connector discovers
these relationships automatically — no manual configuration is needed beyond
enabling `DELEGATED_ACCESS_SCAN`.

**Mode A (`MicrosoftGraphAndUniqueApi`):** A background discovery job
periodically tests which other mailboxes each connected user can access via
Microsoft Graph. When a delegation is detected, the owner's already-ingested
emails become searchable by the delegate through `search_emails` — no additional
ingestion occurs. **Both users must be connected** to the MCP connector: the
owner's emails are only available if the owner has also connected their account
and completed ingestion. Each user's emails remain in their own isolated scope in
the Unique knowledge base.

**Mode B (`MicrosoftGraph`):** The same background discovery job runs and
records delegated mailbox relationships (`granularAccess` is not supported in
Mode B — use `fullAccessOnly`). When `search_emails` is called, it queries each
discovered delegated mailbox via a live Microsoft Graph KQL search alongside the
user's own mailbox. Only delegates with **full mailbox access** can search
delegated mailboxes in Mode B — Microsoft Graph's `$search` parameter requires full
mailbox access and returns HTTP 403 for any search against a partially-delegated
mailbox. See [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)
Microsoft Graph enforces permissions at query time — if the user no longer has
access in Microsoft 365, that query returns no results. No ingestion occurs.

**See also:** [Configuration — DELEGATED_ACCESS_SCAN](./operator/configuration.md#DELEGATED_ACCESS_SCAN)

---

### What happens with delegated access?

**Answer:** When a user has been granted delegated or shared mailbox access in
Microsoft 365, the connector's background jobs detect this and make the delegated
mailbox searchable. There are two jobs:

- **Discovery** (both `fullAccessOnly` and `granularAccess`) — periodically
  checks which connected users have delegated access to another connected user's
  mailbox and records the relationship. This is the only job that runs when
  `DELEGATED_ACCESS_SCAN=fullAccessOnly`.
- **Verification** (`granularAccess` only) — after discovery records a
  delegation, the verification job runs more frequently and confirms exactly which
  folders within the delegated mailbox are currently readable. It also detects
  when folder-level access has been revoked.

**Mode A (`MicrosoftGraphAndUniqueApi`):**

- **Separate scopes, no new ingestion.** Each user's emails are stored in their
  own isolated per-user scope in the Unique knowledge base. Discovery records the
  access relationship — it does not trigger any ingestion. The delegate gains
  search visibility into the owner's scope; nothing is copied or merged.
- **Both users must be connected (both modes).** Discovery only considers
  connected users — if the owner has not connected their MCP account there is
  nothing to discover or search. In Mode A the owner must also have completed
  the initial full sync for their emails to be visible to the delegate.
- **Automatic detection.** New delegated access is picked up automatically on the
  next discovery run — no user action is needed. In `granularAccess` mode,
  folder-level access details are kept up to date by the verification job.
- **Folder filtering.** Delegated mailboxes appear in
  `list_mailboxes_and_directories` alongside the user's own mailbox (with
  `isOwn: false`). Their folder IDs can be passed to the `directories` condition
  in `search_emails` to narrow results to a specific folder.

**Mode B (`MicrosoftGraph`):** Discovery runs and records delegated mailbox
relationships. **Both users must be connected** to the MCP server — discovery
only considers connected users, so if the owner has not connected their account
there is nothing to discover or search. Each `search_emails` call queries the
discovered delegated mailboxes via live Microsoft Graph KQL in addition to the
user's own mailbox. **Only full mailbox access is supported in Mode B** —
Microsoft Graph's `$search` parameter requires full mailbox access and returns
HTTP 403 for any search against a mailbox where you only have folder-level access.
Delegates who only have folder-level access to a mailbox cannot search it in Mode B
at all. See [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)

**See also:** [Configuration — DELEGATED_ACCESS_SCAN](./operator/configuration.md#DELEGATED_ACCESS_SCAN)

---

### When shared inbox access is revoked, are previously ingested emails still accessible?

**Mode A (`MicrosoftGraphAndUniqueApi`):** No — but there is a detection delay
whose length depends on which scan mode is configured.

The connector runs up to two background jobs. Both can detect revocation:

- **Discovery** (both modes) — tests whether the delegate can still access the
  mailbox at all, and deletes the access record on 403/404. Scheduled via
  `DELEGATED_ACCESS_DISCOVERY_CRON_SCHEDULE` (default: every 12 hours; if you
  are using `fullAccessOnly`, consider setting this to 4× per day since
  discovery is the only revocation detection mechanism in that mode).
- **Verification** (`granularAccess` only) — tests each folder individually and
  deletes the access record when no folders remain accessible. Scheduled via
  `DELEGATED_ACCESS_VERIFICATION_CRON_SCHEDULE` (default: every 4 hours).

In `granularAccess` mode, the verification job typically detects revocation
first because it runs more frequently than discovery.

Once a job detects revocation, the access record is removed and the owner's
scope is excluded from the delegate's subsequent `search_emails` queries. During
the window before detection, search results may still include emails from the
revoked mailbox.

The owner's emails are **not affected** — they remain in the owner's own
per-user scope in the Unique knowledge base. Nothing is deleted or modified in
either user's scope as a result of revocation.

**Summary (Mode A):**

| Scan mode | Access revoked — stale results visible until… |
|-----------|------------------------------------------------|
| `fullAccessOnly` | Next discovery run (default every 12 h — recommend configuring 4×/day) |
| `granularAccess` | Next verification run (default every 4 h) |

**Mode B (`MicrosoftGraph`):** Because `search_emails` queries Microsoft Graph
live, revocation takes effect immediately at query time — Microsoft Graph rejects
the call and no results are returned from the revoked mailbox. The access record
is removed immediately after that failed query, so subsequent calls will no
longer include the revoked mailbox.

**See also:** [Configuration — DELEGATED_ACCESS_SCAN](./operator/configuration.md#DELEGATED_ACCESS_SCAN)

---

### Why can't I search emails in a mailbox my colleague shared folders from?

**Answer:** This is a known Microsoft Graph API limitation that affects **Mode B (`MicrosoftGraph`) only**.

When a colleague shares individual folders with you (but has not granted you Full Access to their entire mailbox), Microsoft Graph returns HTTP 403 to any keyword search (`$search`) against that mailbox — regardless of whether you specify a folder or not. The `$search` parameter requires full mailbox access; there is no Microsoft Graph API that supports keyword search in a partially-delegated mailbox. The connector detects the 403, skips that mailbox entirely, and includes a notice in the search response:

> Could not search in mailbox colleague@example.com — Microsoft does not offer an API to search in shared folders from this mailbox.

**Workaround options:**

- **Get Full Access.** Ask your colleague (or an Exchange administrator) to grant you Full Access (Read & Manage) to their mailbox. This allows `$search` queries against the entire mailbox, including the previously shared folders.
- **Use a shared mailbox.** Convert the colleague's mailbox to a Microsoft 365 shared mailbox, connect it to the MCP as its own account, and grant Full Access to everyone who needs to search it. See [Shared inbox configured as a normal inbox](./technical/features.md#3-shared-inbox-configured-as-a-normal-inbox).

**See also:** [Features — Known Limitations](./technical/features.md#known-limitations) — [Configuration — DELEGATED_ACCESS_SCAN](./operator/configuration.md#DELEGATED_ACCESS_SCAN)


## Supported Email Attachment Types

> This section applies to Mode A (`MicrosoftGraphAndUniqueApi`) only. In `MicrosoftGraph` mode, attachments are not ingested.

### Documents
- **PDF** (`.pdf`)
- **Word** (`.doc`, `.docx`, `.dotx`)
- **PowerPoint** (`.ppt`, `.pptx`)
- **Excel** (`.xls`, `.xlsx`)

### Text-based
- **Plain text** (`.txt`)
- **HTML** (`.html`, `.htm`)
- **Markdown** (`.md`)

Emails excluded by inbox filters (`retentionWindowInDays`, `ignoredSenders`, `ignoredContents`) are never ingested.

**See also:** [Configuration](./operator/configuration.md)


## Tool Usage

### How does `search_emails` search?

**Mode A (`MicrosoftGraphAndUniqueApi`):** `search_emails` runs two searches in parallel — semantic search against the Unique knowledge base and a KQL keyword search against Microsoft Graph — then merges and deduplicates the results. It supports natural-language queries and returns semantically relevant results even when exact keywords do not match. The input requires two arrays: `uniqueSemanticSearchQueries` (semantic, 1–10 entries) and `msGraphKeywordSearchQueries` (KQL, 1–10 entries), both addressing the same user question from different angles. A `limit` parameter on each entry (100–200 for semantic, 1–100 for KQL) controls the maximum per-query results. Search results may be incomplete while full sync is in progress — a `syncWarning` is returned in that case.

**Mode B (`MicrosoftGraph`):** `search_emails` queries Microsoft Graph directly using KQL keyword search only. Only `msGraphKeywordSearchQueries` is accepted. There is no semantic search and no Knowledge Base interaction. Folder filtering via the `directories` field is supported for your own mailbox and for mailboxes where you have Full Access delegation. Search is **not supported at all** for mailboxes where you only have folder-level (partial) access — Microsoft Graph rejects any search request against such mailboxes. See [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)

**See also:** [Tools — search_emails](./technical/tools.md#search_emails)

### How do I filter search results to a specific folder?

**Answer:** Use the `list_mailboxes_and_directories` tool to get the folder tree, then pass the folder ID in the `conditions` array using the `directories` field. Well-known system folders like "Inbox", "Sent Items", and "Drafts" can be used by name directly — no need to call `list_mailboxes_and_directories` for those.

```json
// Search within a specific folder by name
{
  "search": "quarterly report",
  "conditions": [
    {
      "directories": { "value": ["Inbox"], "operator": "in" }
    }
  ]
}

// Search within a custom folder by ID (from list_mailboxes_and_directories)
{
  "search": "project update",
  "conditions": [
    {
      "directories": { "value": ["<folder-id-from-list_mailboxes_and_directories>"], "operator": "in" }
    }
  ]
}
```

**Mode B (`MicrosoftGraph`):** Folder filtering is supported for your own mailbox and for mailboxes where you have Full Access delegation. Pass the folder ID (from `list_mailboxes_and_directories`) or a well-known name in the `directories` field of the relevant `msGraphKeywordSearchQueries` entry. Note: if you only have folder-level (partial) access to a mailbox, search does not work against it at all — not just when filtering by folder. The response will include a notice and no results are returned from that mailbox. See [Why can't I search emails in a mailbox my colleague shared folders from?](#Why-can't-I-search-emails-in-a-mailbox-my-colleague-shared-folders-from?)

**See also:** [Tools — list_mailboxes_and_directories](./technical/tools.md#list_mailboxes_and_directories) — [Tools — search_emails](./technical/tools.md#search_emails)

### Can I attach files when creating a draft email?

**Answer:** Yes. The `create_draft_email` tool accepts attachments as an array of objects with `fileName` and `data` fields. The `data` field accepts:

- A **base64-encoded data URI** (`data:[mediatype];base64,<data>`) — works in all deployment modes
- A **Unique content URI** (`unique://content/{contentId}`) — only in cluster-local mode we expect the attachment to be in the chat or in knowledge base. In external mode this URI is unresolvable and the attachment will fail.

If one or more attachments fail to upload, the draft is still created and the failed attachments are listed in the response.

**See also:** [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### Can I create drafts in a shared mailbox?

**Answer:** Yes. Pass the shared mailbox UPN as the `mailbox` parameter (e.g. `"support@company.com"`). The signed-in user must have been granted at least **Send As** or **Full Access** permissions to the shared mailbox in Microsoft 365 — the Graph API enforces this at request time.

Both draft types work with shared mailboxes:

- **Fresh draft** (`type: "draft"`) — pass `mailbox`, `subject`, `toRecipients`, and optionally `ccRecipients`.
- **Reply-all draft** (`type: "reply"`) — pass `mailbox` and `inReplyToMessageId`. Graph pre-fills all original recipients automatically.

Omitting `mailbox` creates the draft in the signed-in user's own mailbox.

**See also:** [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### Why does a reply draft in a shared mailbox appear in Drafts instead of in the thread in Outlook Web?

**Answer:** This is a known Outlook Web quirk, not a bug. When a reply draft is created via Microsoft Graph in a shared mailbox, Outlook Web places it in the shared mailbox **Drafts** folder rather than showing it inline within the original conversation thread. The draft is fully intact — all recipients are pre-filled and the reply chain is preserved — and it sends correctly when you open it from Drafts and click Send.

**Outlook desktop** does not have this quirk: reply drafts appear and behave normally within the thread.

If you are reviewing or sending the draft, open it from the shared mailbox Drafts folder in Outlook Web, or use Outlook desktop where thread placement is correct.

**See also:** [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### What does `reconnect_inbox` do?

**Answer:** (Mode A — `MicrosoftGraphAndUniqueApi` — only) `reconnect_inbox` creates a new Microsoft Graph subscription only if none exists or the existing one has expired. If the subscription is within 15 minutes of expiry, it returns `expiring_soon` without making changes (renewal is automatic). If the subscription is active with more than 15 minutes remaining, it returns `already_active`. Use it when:

- `verify_inbox_connection` reports the subscription as `expired` or `not_configured`
- New emails stopped appearing in search results
- The user's Microsoft refresh token has been renewed after a period of inactivity

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline) — [Tools — reconnect_inbox](./technical/tools.md#reconnect_inbox)

### What does `delete_inbox_data` do?

**Answer:** (Mode A — `MicrosoftGraphAndUniqueApi` — only) `delete_inbox_data` permanently removes the user's inbox connection and all associated data, including ingested email content in the Unique knowledge base. See [Flows — Subscription Lifecycle](./technical/flows.md#Subscription-Creation-and-Renewal-Lifecycle) for details.


## Sync

> All questions in this section apply to **Mode A (`MicrosoftGraphAndUniqueApi`) only**. There is no sync pipeline in `MicrosoftGraph` mode.

### What is the difference between full sync and live catch-up?

**Answer:**

| | Full Sync | Live Catch-Up |
|-|-----------|---------------|
| Purpose | Ingest emails within the configured time frame and filters | Ingest new emails in real time |
| Trigger | Automatic after connection | Microsoft Graph webhook notification |
| Transport | Direct Graph API (paginated) | Direct (inline, synchronous per-message) |
| State | `ready` / `running` / `waiting-for-ingestion` / `paused` / `failed` | `ready` / `running` / `failed` |
| Resumable | Yes — via `fullSyncNextLink` cursor | N/A (each notification is independent) |

Full sync states: `ready`, `running`, `waiting-for-ingestion`, `paused`, `failed`. See [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline) for more detail.

Both pipelines run concurrently after connection.
Full sync uploads batches via the Unique KB ingestion API and checks if Unique KB ingested majority of the documents before continuing.
Live catch-up uploads batches via the Unique KB ingestion API but does not wait for Unique KB to ingest them. This process makes full sync wait longer because
it contributes to the in-progress count that full sync monitors during `waiting-for-ingestion`.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline) — [Flows](./technical/flows.md)

### How do I check sync progress?

**Answer:** Use the `sync_progress` tool. It returns the current `fullSyncState`, counters (expected total, scheduled for ingestion, skipped, failed), and ingestion stats (finished, in progress).

Search results are incomplete while `fullSyncState` is `running` or `waiting-for-ingestion`. The `search_emails` tool returns a `syncWarning` field in this case.

**See also:** [Tools — sync_progress](./technical/tools.md#sync_progress)

### Why is my full sync stuck in `waiting-for-ingestion`?

**Answer:** Full sync enters `waiting-for-ingestion` after uploading all email batches and waits for the Unique knowledge base to confirm that majority of queued messages are processed. Because live catch-up ingests emails directly to the Unique KB inline, it contributes to the in-progress count that full sync monitors. High live catch-up activity can extend the time full sync spends in this state. This is normal behavior.

If the sync has been in `waiting-for-ingestion` with a stale heartbeat for more than 5 minutes, the recovery scheduler will automatically re-trigger the ingestion check.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline)

### Why is my full sync stuck in `running`?

**Answer:** The most common causes are:

- Large mailboxes (100,000+ emails) — full sync fetches pages of 100 messages sequentially
- Transient Microsoft Graph rate limits
- Network issues causing slow page fetches

If the heartbeat is stale for more than 20 minutes, the recovery scheduler automatically retriggers the sync. Check `sync_progress` for the current counters to verify the sync is making progress.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline)

### What happens if full sync is interrupted (restart, crash)?

**Answer:** Full sync is resumable. The `fullSyncNextLink` column stores the Microsoft Graph pagination cursor. On restart, the recovery scheduler detects the stale heartbeat and retriggers. The sync resumes from the stored cursor rather than starting over.

If the cursor has expired (HTTP 410), the sync falls back to a fresh query filtered from the oldest recorded creation date.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline)

### Why are new emails not appearing in search results?

**Answer:** Check the following:

1. **Active subscription** — verify via `verify_inbox_connection`. If the subscription is `expired` or `not_configured`, call `reconnect_inbox`.
2. **Live catch-up state** — check `sync_progress` for `liveCatchUpState`. If `failed`, the recovery scheduler resets it automatically within 5 minutes — no user action is required. Operators can monitor pod logs if the issue persists.
3. **Inbox filters** — the email may match an `ignoredSenders` or `ignoredContents` filter.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline) — [Flows](./technical/flows.md)

### What happens to emails sent during full sync?

**Answer:** Live catch-up runs concurrently with full sync. New emails are processed by live catch-up immediately — the watermark is always initialized on inbox creation, so notifications are never buffered.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline)

### Why are deleted emails still appearing in search results?

**Answer:** Email deletion detection is handled asynchronously via two mechanisms: individual email deletions are detected when Microsoft moves the email to Deleted Items (an ignored folder), and entire folder deletions are detected by directory sync on its 5-minute delta cycle. There may be a brief delay between deletion and removal from search results.

**Known limitation — bulk deletion with immediate permanent removal:** The server processes emails found in the Deleted Items folder and removes them from the Unique knowledge base. If the user permanently deletes emails from Deleted Items (e.g. via "Empty Folder") before the server finishes processing them, those emails are no longer visible to the server and cannot be cleaned up. They will persist in the Unique knowledge base until the content expiration policy removes them.

**See also:** [Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline) — [Flows](./technical/flows.md) — [Limitations and Constraints](./README.md#Limitations-and-Constraints)


## Authentication & Permissions

### Do any permissions require admin consent?

**Answer:** No. All permissions are delegated and do not require admin consent. Users can connect and grant consent themselves without IT involvement.

**See also:** [Permissions](./technical/permissions.md) for the full reference with least-privilege justification.

### Why does the server need `Mail.ReadWrite` if it mostly reads emails?

**Answer:** `Mail.ReadWrite` serves dual purposes: it provides read access for email sync and search (full sync, live catch-up), and write access for the `create_draft_email` tool which creates email messages in the user's mailbox via `POST /me/messages`. Since `Mail.ReadWrite` already includes full read access, the narrower `Mail.Read` and `Mail.ReadBasic` scopes are not needed.

Delete detection does not require write access — it works by observing `created` change notifications on ignored folders (such as Deleted Items), not by moving emails.

In addition, `Mail.ReadWrite.Shared` is requested at OAuth time for delegated-access support. It is a no-op when `DELEGATED_ACCESS_SCAN=disabled` — no shared mailbox data is accessed — but it always appears on the Microsoft consent screen.

**See also:** [Permissions](./technical/permissions.md) — [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### Why can't I use application permissions instead of delegated?

**Answer:** Application permissions would require tenant administrators to create Application Access Policies via PowerShell for each user. This defeats the self-service model where users connect their own accounts without IT involvement.

Delegated permissions also ensure the server can only access emails the signed-in user can access — not mailboxes of other users.

**See also:** [Why Delegated (Not Application) Permissions](./technical/permissions.md#Why-Delegated-(Not-Application)-Permissions)

### Why do I need a client ID and client secret?

**Answer:** Microsoft Graph API uses OAuth 2.0. The `CLIENT_ID` identifies your app registration and the `CLIENT_SECRET` proves to Microsoft that your server is the legitimate application. Both are used server-side only — the client secret is never sent to AI clients.

**See also:** [Operator Configuration](./operator/configuration.md)

### What is the "login flicker" when users reconnect?

**Answer:** When reconnecting, users may see a brief "flicker" — a rapid redirect sequence through Microsoft's login pages. This is **normal** Microsoft OAuth behavior. First-time connections show the full consent screen; subsequent reconnections are automatic.

**See also:** [Authentication — User Reconnection Experience](./operator/authentication.md#Understanding-Consent-Flows) for details.

### What happens when a user's Microsoft refresh token expires?

**Answer:** The server can no longer refresh access tokens for that user. All Microsoft Graph operations fail until the user reconnects via the `reconnect_inbox` tool.

Refresh tokens expire after approximately 90 days of inactivity (Microsoft limit, not configurable) or when the user revokes consent.

**See also:** [Microsoft Token Refresh Flow](./technical/flows.md#Microsoft-Token-Refresh-Flow)


## Security

### How are Microsoft tokens stored?

**Answer:** Microsoft access and refresh tokens are encrypted at rest using AES-256-GCM and stored in the `user_profiles` table. They are never sent to AI clients — the server issues separate opaque MCP bearer tokens for all client interactions.

**See also:** [Token Security](./technical/security.md#Microsoft-Tokens-(Encrypted-at-Rest))

### How are MCP tokens stored?

**Answer:** MCP tokens are opaque 512-bit random values (`randomBytes(64)`). The full token value is stored directly in the `tokens` table and used for equality comparison during validation. Token unguessability is the security property — not one-way hashing.

**See also:** [MCP Tokens](./technical/security.md#MCP-Tokens-(Opaque-Random-Values))

### Why does the server use PKCE?

**Answer:** PKCE (Proof Key for Code Exchange) prevents authorization code interception. Even if an attacker observes the redirect, they cannot exchange the authorization code without the code verifier that was generated client-side. PKCE is required by OAuth 2.1 for all authorization code flows.

**See also:** [OAuth 2.1 with PKCE](./technical/security.md#OAuth-2.1-with-PKCE)

### What happens if a refresh token is stolen?

**Answer:** The token family revocation mechanism detects reuse. Each refresh token has a `familyId`, `generation`, and `usedAt` timestamp. If a token is presented after it has already been used (indicating possible theft), the entire token family is revoked and the user must re-authenticate.

**See also:** [Refresh Token Rotation](./technical/security.md#Refresh-Token-Rotation)


## Configuration

### What redirect URI should I configure in Entra ID?

**Answer:** The redirect URI must be:

```
https://<your-domain>/auth/callback
```

This must match exactly — including protocol, domain, and path — in both the Entra ID app registration and the `SELF_URL` environment variable. The redirect URI is derived as `<SELF_URL>/auth/callback`.

**See also:** [Configuration](./operator/configuration.md)

### Why do I need a webhook secret?

**Answer:** The `MICROSOFT_WEBHOOK_SECRET` validates that incoming webhook notifications actually come from Microsoft Graph. It is sent to Microsoft when creating subscriptions and returned in every notification payload. The server rejects any notification where the `clientState` does not match.

**Generate:** `openssl rand -hex 64` (128 characters)

(Mode A only — in `MicrosoftGraph` mode, no webhook subscriptions are created.)

**See also:** [Webhook Validation](./technical/security.md#Webhook-Validation) — [Configuration](./operator/configuration.md)

### What happens if I change the encryption key?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect via `reconnect_inbox`. There is no zero-downtime rotation — plan for a maintenance window.

**See also:** [Secret Management](./operator/authentication.md#Secret-Management) for the full rotation procedure

### What happens if I change the webhook secret?

**Answer:** All existing Microsoft Graph subscriptions will fail validation. Notifications will be rejected until subscriptions are recreated. All users must call `reconnect_inbox` after the change.

**See also:** [Secret Management](./operator/authentication.md#Secret-Management) for the full rotation procedure

### What happens if I change the client secret?

**Answer:** Update the Kubernetes secret and restart the pods. Users do not need to reconnect — the server uses the new secret transparently. This supports zero-downtime rotation.

**See also:** [Secret Management](./operator/authentication.md#Secret-Management) for the full rotation procedure

### What does `INGESTION_DEFAULT_MAIL_FILTERS` do?

**Answer:** (Mode A — `MicrosoftGraphAndUniqueApi` — only) `INGESTION_DEFAULT_MAIL_FILTERS` is a JSON object that controls which emails are ingested during both full sync and live catch-up. It supports three filters: `retentionWindowInDays` (positive integer — required, the application will not start without it; all ingested emails have an expired at date which is computed using receivedDateTime + retentionWindowInDays), `ignoredSenders` (RegExp patterns matching sender addresses), and `ignoredContents` (RegExp patterns matching subject or body).

When the filters are updated and the service is redeployed, all user inbox configurations are updated. Both full sync and live catch-up use the new filters. Previously ingested emails that would now be filtered are not automatically removed. See [Configuration](./operator/configuration.md) for the full filter reference.

**See also:** [Configuration](./operator/configuration.md)


## Deployment

### Why is RabbitMQ required?

**Answer:** Microsoft requires webhook endpoints to respond within 10 seconds (Microsoft limit, not configurable). Processing a live catch-up notification involves acquiring database locks, querying Microsoft Graph, and uploading emails to the knowledge base — which can take longer. RabbitMQ decouples receipt from processing: the webhook controller enqueues the notification and returns `202 Accepted` immediately. The consumer then handles email fetching and ingestion, after the response has already been sent. RabbitMQ is also used for full sync inter-batch orchestration and other internal events.

**See also:** [Architecture](./technical/architecture.md)

### What happens if RabbitMQ is unavailable?

**Answer:** Webhook trigger notifications cannot be published to the queue. The webhook controller will fail to enqueue them and return an error to Microsoft. Microsoft will retry the notification. The server will resume processing once RabbitMQ is available and Microsoft retries, but notifications that exceed Microsoft's retry window may be lost.

Full sync relies on RabbitMQ for inter-batch orchestration — without RabbitMQ, in-progress full syncs complete their current batch but no new batches are triggered. See [Disaster Recovery — Scenario 2](./operator/disaster-recovery.md#Scenario-2:-RabbitMQ-Loss) for details.

Live Catch-Up stalls while RabbitMQ is unavailable. Once RabbitMQ recovers, either the first notification from MsGraph or the 30-minute catch-up cron re-triggers processing, which picks up missed messages by querying from the last watermark.

**Mode B (`MicrosoftGraph`):** The service loses its RabbitMQ connection and cannot function until it is restored; no email data is lost.

### What happens if PostgreSQL is unavailable?

**Answer:** All operations that require database access will fail: inbox lock acquisition (blocking live catch-up and full sync), token validation (blocking all tool calls), and sync state updates. The service will resume once PostgreSQL is restored.

### Can one deployment serve multiple Microsoft tenants?

**Answer:** Yes. Configure the Entra ID app registration with "Accounts in any organizational directory" (multi-tenant). When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant referencing your app registration. One deployment serves all tenants.

**See also:** [Architecture](./technical/architecture.md)


## Disaster Recovery

### What do I do if a core infrastructure component fails?

**Mode A (`MicrosoftGraphAndUniqueApi`):**
- PostgreSQL loss — all stored OAuth tokens and sync state are gone; every user must re-authenticate via the standard OAuth flow in their MCP client. No tool call is needed — OAuth completion automatically recreates the subscription and triggers a full sync.
- RabbitMQ loss — in-progress full syncs stall after the current batch; live catch-up trigger delivery is blocked but any in-progress run completes. No re-authentication needed. Live catch-up resumes automatically once RabbitMQ is restored.
- Unique Knowledge Base loss — ingested email content must be re-ingested; each affected user must call `restart_full_sync` from their own MCP session (debug mode required).

**Mode B (`MicrosoftGraph`):**
- PostgreSQL loss — all stored OAuth tokens are gone; users must reconnect via the standard OAuth flow in their MCP client. No tool call is required. No sync data exists to recover.
- RabbitMQ loss — the service cannot connect; no email data is lost. Recovery: restore RabbitMQ, restart pods. No user action required.
- Unique Knowledge Base loss — no email data is stored there in Mode B, so search is unaffected. Restore the KB to restore full service connectivity. No user action required.

**See also:** [Disaster Recovery Runbook](./operator/disaster-recovery.md)


## Related Documentation

- [Architecture](./technical/architecture.md) — System components and module descriptions
- [Flows](./technical/flows.md) — Sequence diagrams for all major flows
- [Permissions](./technical/permissions.md) — Required scopes and least-privilege justification
- [Security](./technical/security.md) — Encryption, PKCE, token rotation, and threat model
- [Tools](./technical/tools.md) — Full reference for all MCP tools
- [Operator Guide](./operator/README.md) — Deployment and operations
