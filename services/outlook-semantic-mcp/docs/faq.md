<!-- confluence-page-id: 2061107213 -->
<!-- confluence-space-key: PUBDOC -->

# FAQ

## General

### What type of MCP server is this?

**Answer:** The Outlook Semantic MCP Server is a **hybrid MCP server** — it exposes 10 user-facing MCP tools that AI clients invoke on demand (plus 4 additional tools available only in debug mode), and it also automatically ingests the user's email history and live mail into the Unique knowledge base in the background.

**What it does:**

- Automatically ingests the user's complete email history into the Unique knowledge base after connection
- Exposes 10 tools (plus 4 debug-mode tools) for searching emails, managing drafts, listing folders, and monitoring sync status
- Keeps the knowledge base up to date in real time via webhook-driven live catch-up
- Requires no manual setup beyond the initial connection

**What the user sees:**

- An initial OAuth consent screen to connect their Outlook account
- 10 MCP tools available in their AI client immediately after connection (14 with debug mode enabled)
- Search results that may be incomplete while the initial full sync is running (a `syncWarning` is returned by `search_emails`)

**See also:** [Architecture](./technical/architecture.md) — [Tools](./technical/tools.md)

### What tools are available?

**Answer:** The server exposes 10 user-facing tools:

| Category | Tools |
|----------|-------|
| Email Search | `search_emails`, `open_email_by_id` |
| Draft Creation | `create_draft_email` |
| Contact Lookup | `lookup_contacts` |
| Mailbox Utilities | `list_categories`, `list_folders` |
| Subscription Management | `verify_inbox_connection`, `reconnect_inbox`, `remove_inbox_connection` |
| Sync Monitoring | `sync_progress` |

An additional 4 tools are available only when the server is running in debug mode (`MCP_DEBUG_MODE=enabled`): `run_full_sync`, `pause_full_sync`, `resume_full_sync`, `restart_full_sync`. These are intended for development and troubleshooting and are not exposed in production deployments.

**See also:** [Tools Reference](./technical/tools.md) — [Debug Mode Tools](./technical/tools.md#debug-mode-tools)

### Do I need to do anything after connecting?

**Answer:** No. After granting consent, the server automatically creates a Microsoft Graph subscription and starts ingesting emails within the operator-configured time frame and filters (see [Inbox Filters](./technical/full-sync.md#inbox-filters)). The 10 tools become available immediately (14 with debug mode enabled). Search results may be incomplete while the initial full sync is running.

## Authentication & Permissions

### Do any permissions require admin consent?

**Answer:** No. All five permissions used by the server are **delegated permissions that do not require admin consent**. Users can connect and grant consent themselves without IT involvement.

The permissions are: `User.Read`, `Mail.ReadWrite`, `MailboxSettings.Read`, `People.Read`, `offline_access`.

**See also:** [Permissions](./technical/permissions.md)

### Why does the server need `Mail.ReadWrite` if it mostly reads emails?

**Answer:** `Mail.ReadWrite` serves dual purposes: it provides read access for email sync and search (full sync, live catch-up), and write access for the `create_draft_email` tool which creates email messages in the user's mailbox via `POST /me/messages`. Since `Mail.ReadWrite` already includes full read access, the narrower `Mail.Read` and `Mail.ReadBasic` scopes are not needed.

Delete detection does not require write access — it works by observing `created` change notifications on ignored folders (such as Deleted Items), not by moving emails.

**See also:** [Permissions](./technical/permissions.md) — [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### Why can't I use application permissions instead of delegated?

**Answer:** Application permissions would require tenant administrators to create Application Access Policies via PowerShell for each user. This defeats the self-service model where users connect their own accounts without IT involvement.

Delegated permissions also ensure the server can only access emails the signed-in user can access — not mailboxes of other users.

**See also:** [Why Delegated (Not Application) Permissions](./technical/permissions.md#why-delegated-not-application-permissions)

### Why do I need a client ID and client secret?

**Answer:** Microsoft Graph API uses OAuth 2.0. The `CLIENT_ID` identifies your app registration and the `CLIENT_SECRET` proves to Microsoft that your server is the legitimate application. Both are used server-side only — the client secret is never sent to AI clients.

**See also:** [Operator Configuration](./operator/configuration.md)

### What happens when a user's Microsoft refresh token expires?

**Answer:** The server can no longer refresh access tokens for that user. All Microsoft Graph operations fail until the user reconnects via the `reconnect_inbox` tool.

Refresh tokens expire after approximately 90 days of inactivity or when the user revokes consent.

**See also:** [Microsoft Token Refresh Flow](./technical/flows.md#microsoft-token-refresh-flow)

## Configuration

### What redirect URI should I configure in Entra ID?

**Answer:** The redirect URI must be:

```
https://<your-domain>/auth/callback
```

This must match exactly — including protocol, domain, and path — in both the Entra ID app registration and the `MICROSOFT_REDIRECT_URI` environment variable.

**See also:** [Configuration](./operator/configuration.md)

### Why do I need a webhook secret?

**Answer:** The `MICROSOFT_WEBHOOK_SECRET` validates that incoming webhook notifications actually come from Microsoft Graph. It is sent to Microsoft when creating subscriptions and returned in every notification payload. The server rejects any notification where the `clientState` does not match.

**Generate:** `openssl rand -hex 64` (128 characters)

**See also:** [Webhook Validation](./technical/security.md#webhook-validation) — [Configuration](./operator/configuration.md)

### What happens if I change the encryption key?

**Answer:** All stored Microsoft tokens become unreadable. All users must reconnect via `reconnect_inbox` to re-authenticate and obtain fresh tokens. There is no zero-downtime rotation — plan for a maintenance window.

**See also:** [ENCRYPTION_KEY Rotation](./technical/security.md#rotation-procedures)

### What happens if I change the webhook secret?

**Answer:** All existing Microsoft Graph subscriptions will fail validation because they were created with the old secret. Notifications will be rejected until subscriptions are recreated with the new secret.

To rotate: update the `MICROSOFT_WEBHOOK_SECRET` environment variable, then have all users call `reconnect_inbox` to recreate their subscriptions.

**See also:** [MICROSOFT_WEBHOOK_SECRET Rotation](./technical/security.md#rotation-procedures)

### What happens if I change the client secret?

**Answer:** Update the Kubernetes secret and restart the pods. Users do not need to reconnect — the server uses the new secret for token refresh operations transparently.

**Rotation process:** Create new secret in Entra ID → Update Kubernetes secret → Restart pods → Verify authentication → Delete old secret from Entra ID.

**See also:** [Client Secret Rotation](./technical/security.md#rotation-procedures)

### What does `DEFAULT_MAIL_FILTERS` do?

**Answer:** `DEFAULT_MAIL_FILTERS` is a JSON object that controls which emails are ingested during full sync. Emails that match any filter are skipped:

| Filter | Effect |
|--------|--------|
| `ignoredBefore` | Skips emails created before this ISO 8601 date |
| `ignoredSenders` | Skips emails whose sender matches any RegExp pattern. Values must use `/pattern/flags` format (e.g. `/^noreply@/i`). |
| `ignoredContents` | Skips emails whose subject or body matches any RegExp pattern. Values must use `/pattern/flags` format (e.g. `/unsubscribe/i`). |

When the filters are updated and the service is redeployed, all user inbox configurations are updated. The next full sync uses the new filters. Previously ingested emails that would now be filtered are not automatically removed.

**See also:** [Inbox Filters](./technical/full-sync.md#inbox-filters) — [Configuration](./operator/configuration.md)

## Sync

### What is the difference between full sync and live catch-up?

**Answer:**

| | Full Sync | Live Catch-Up |
|-|-----------|---------------|
| Purpose | Ingest emails within the configured time frame and filters | Ingest new emails in real time |
| Trigger | Automatic after connection | Microsoft Graph webhook notification |
| Transport | Direct Graph API (paginated) | RabbitMQ (asynchronous) |
| State | `ready` / `running` / `waiting-for-ingestion` / `failed` | `ready` / `running` / `failed` |
| Resumable | Yes — via `fullSyncNextLink` cursor | N/A (each notification is independent) |

Both pipelines run concurrently after connection and both contribute to the Unique knowledge base ingestion queue.

**See also:** [Full Sync](./technical/full-sync.md) — [Live Catch-Up](./technical/live-catchup.md)

### How do I check sync progress?

**Answer:** Use the `sync_progress` tool. It returns the current `fullSyncState`, counters (expected total, scheduled for ingestion, skipped, failed), and ingestion stats (finished, in progress).

Search results are incomplete while `fullSyncState` is `running` or `waiting-for-ingestion`. The `search_emails` tool returns a `syncWarning` field in this case.

**See also:** [Tools — sync_progress](./technical/tools.md#sync_progress)

### Why is my full sync stuck in `waiting-for-ingestion`?

**Answer:** Full sync enters `waiting-for-ingestion` after uploading all email batches and waits for the Unique knowledge base to confirm all queued messages are processed. Because live catch-up uploads its own batches to the same ingestion queue, high live catch-up activity extends the time full sync spends in this state. This is normal behavior.

If the sync has been in `waiting-for-ingestion` with a stale heartbeat for more than 5 minutes, the recovery scheduler will automatically re-trigger the ingestion check.

**See also:** [Stale Sync Recovery](./technical/full-sync.md#stale-sync-recovery)

### Why is my full sync stuck in `running`?

**Answer:** The most common causes are:

- Large mailboxes (100,000+ emails) — full sync fetches pages of 100 messages sequentially
- Transient Microsoft Graph rate limits
- Network issues causing slow page fetches

If the heartbeat is stale for more than 20 minutes, the recovery scheduler automatically retriggers the sync. Check `sync_progress` for the current counters to verify the sync is making progress.

**See also:** [Stale Sync Recovery](./technical/full-sync.md#stale-sync-recovery)

### What happens if full sync is interrupted (restart, crash)?

**Answer:** Full sync is resumable. The `fullSyncNextLink` column stores the Microsoft Graph pagination cursor. On restart, the recovery scheduler detects the stale heartbeat and retriggers. The sync resumes from the stored cursor rather than starting over.

If the cursor has expired (HTTP 410), the sync falls back to a fresh query filtered from the oldest recorded creation date.

**See also:** [How Batching Works](./technical/full-sync.md#how-batching-works)

### Why are new emails not appearing in search results?

**Answer:** Check the following:

1. **Active subscription** — verify via `verify_inbox_connection`. If the subscription is `expired` or `not_configured`, call `reconnect_inbox`.
2. **Live catch-up state** — check `sync_progress` for `liveCatchUpState`. If `failed`, the recovery scheduler will reset it within 5 minutes.
3. **Inbox filters** — the email may match an `ignoredSenders` or `ignoredContents` filter.
4. **Watermarks not initialized** — if full sync has not yet initialized the watermarks, live catch-up buffers incoming notifications until they are. Check if `fullSyncState` is `running`.

**See also:** [Live Catch-Up](./technical/live-catchup.md) — [Subscription Management](./technical/subscription-management.md)

### What happens to emails sent during full sync?

**Answer:** Live catch-up runs concurrently with full sync. New emails arriving during full sync are processed immediately by live catch-up (once full sync has initialized the watermarks). Live catch-up buffers notifications only if another live catch-up consumer is already running or if the watermarks have not been initialized yet.

**See also:** [Relation to Full Sync](./technical/live-catchup.md#relation-to-full-sync)

### Why are deleted emails still appearing in search results?

**Answer:** Email deletion detection is handled asynchronously:

- When a user deletes an email, Microsoft moves it to Deleted Items first. This generates a `created` change notification for the Deleted Items folder. The server detects the email is now in an ignored folder and removes it from the knowledge base.
- Deleted Items is processed on the next live catch-up cycle. There may be a brief delay between deletion and removal from search results.
- If an entire folder was deleted, directory sync detects this on its 5-minute delta cycle.

**See also:** [Directory Sync](./technical/directory-sync.md) — [Live Catch-Up](./technical/live-catchup.md)

## Tool Usage

### How does `search_emails` search?

**Answer:** `search_emails` performs semantic search against the Unique knowledge base — not a keyword search against a local index. It supports natural language queries and returns semantically relevant results even when exact words do not match.

Optional filters: `folderId` (from `list_folders`), `fromSenders`, `toRecipients`, `ccRecipients` (full or partial email addresses), `startDate`, `endDate`, `limit`.

Search results may be incomplete while full sync is in progress. A `syncWarning` field is returned in that case.

**See also:** [Tools — search_emails](./technical/tools.md#search_emails)

### How do I filter search results to a specific folder?

**Answer:** Use the `list_folders` tool to get the folder tree, then pass the folder's `id` as the `folderId` parameter to `search_emails`.

```json
// 1. List folders to get IDs
{ "tool": "list_folders" }

// 2. Search within a specific folder
{ "tool": "search_emails", "folderId": "<folder-id-from-list_folders>", "query": "..." }
```

**See also:** [Tools — list_folders](./technical/tools.md#list_folders) — [Tools — search_emails](./technical/tools.md#search_emails)

### Can I attach files when creating a draft email?

**Answer:** Yes. The `create_draft_email` tool accepts attachments as an array of objects with `filename`, `contentType`, and `content` fields. The `content` field accepts:

- A **base64-encoded data URI** (`data:[mediatype];base64,<data>`) — works in all deployment modes
- A **Unique content URI** (`unique://content/{contentId}`) — only in cluster-local mode we expect the attachment to be in the chat or in knowledge base. In external mode this URI is unresolvable and the attachment will fail.

If one or more attachments fail to upload, the draft is still created and the failed attachments are listed in the response.

**See also:** [Tools — create_draft_email](./technical/tools.md#create_draft_email)

### What does `reconnect_inbox` do?

**Answer:** `reconnect_inbox` forces creation of a new Microsoft Graph subscription regardless of the current subscription state. This restarts live catch-up and triggers a new full sync. Use it when:

- `verify_inbox_connection` reports the subscription as `expired` or `not_configured`
- New emails stopped appearing in search results
- The user's Microsoft refresh token has been renewed after a period of inactivity

**See also:** [Subscription Management](./technical/subscription-management.md) — [Tools — reconnect_inbox](./technical/tools.md#reconnect_inbox)

### What does `remove_inbox_connection` do?

**Answer:** `remove_inbox_connection` permanently removes the user's inbox connection: it deletes the Microsoft Graph subscription, removes all folder data and root scopes from the Unique knowledge base, and clears the inbox configuration. Previously ingested emails remain in the knowledge base until explicitly deleted.

**See also:** [Subscription Management](./technical/subscription-management.md#remove_inbox_connection)

## Data Privacy & Storage

### Does the MCP server store my emails?

**Answer:** No. The Outlook Semantic MCP Server stores **no email content** in its own database. Emails are fetched from Microsoft Graph into memory and forwarded directly to the Unique knowledge base for indexing. Nothing from the email body, subject, sender, or recipients is written to the MCP server's PostgreSQL database.

What the MCP server's PostgreSQL database **does** store:

- Encrypted Microsoft OAuth tokens (access + refresh) — used to call Microsoft Graph on your behalf
- Opaque MCP bearer tokens — used to authenticate tool calls from the AI client
- Sync state and progress counters — which page of emails has been processed, etc.
- Outlook folder structure — folder names and IDs only, no message content
- Microsoft Graph subscription IDs and expiry dates

**See also:** [Data Classification and Flow](./technical/security.md#data-classification-and-flow)

### Where is my email content stored?

**Answer:** Email content (subject, body, sender, recipients, and metadata) is stored in the **Unique knowledge base**, not in the MCP server itself. It is indexed there for semantic search and is accessible via the `search_emails` tool.

The Unique knowledge base organizes each user's emails into a dedicated root scope — logically separating one user's data from another's within the platform.

**See also:** [Knowledge Base Data Isolation](./technical/security.md#knowledge-base-data-isolation)

### Who can access my email data once it is ingested?

**Answer:** Access to ingested email data operates at two levels:

**Via the MCP server (tool layer):** The `search_emails` tool only returns results from the authenticated user's own scope. One user's MCP session cannot query another user's emails.

**Via the Unique platform (platform layer):** Email content stored in the Unique knowledge base is subject to Unique's own access control model. This includes:

- The MCP server's service account, which has write access to the ingestion and scope management APIs used during sync
- Unique platform administrators with API access — email scopes are not surfaced in the Unique Knowledge Base UI, but can be enumerated via the Unique API (e.g. `scopesByCompany`) or accessed directly via the database.

Organizations with strict email privacy requirements should control who has API and database access to the Unique platform.

**See also:** [Knowledge Base Data Isolation](./technical/security.md#knowledge-base-data-isolation)

### Can an operator with database access read my emails?

**Answer:** No — not from the MCP server's PostgreSQL database. It contains no email content. An operator with direct database access would see only encrypted OAuth tokens, opaque random bearer tokens, sync state, and folder metadata.

Decrypting the stored Microsoft tokens would require the `ENCRYPTION_KEY` value, which should be stored in a Kubernetes Secret and not accessible to most operators.

Access to the email content itself requires access to the Unique knowledge base, which is governed separately by Unique platform policies.

**See also:** [Data Classification and Flow](./technical/security.md#data-classification-and-flow)

### What happens to my email data when I disconnect?

**Answer:** Calling `remove_inbox_connection`:

- Deletes the Microsoft Graph subscription (stops future email sync)
- Removes the per-user root scopes from the Unique knowledge base
- Clears the inbox configuration and folder sync data from PostgreSQL

**Previously ingested email content is not automatically purged.** Emails ingested before disconnection remain in the knowledge base until explicitly deleted through the Unique platform. Operators who need to fully remove a user's data must initiate that deletion separately via Unique platform tooling.

**See also:** [Data Removal](./technical/security.md#data-removal)

### What email data is actually ingested into the knowledge base?

**Answer:** The following fields from each email are ingested:

- Subject
- Body (plain text and/or HTML)
- Sender (name and email address)
- To, CC, and BCC recipients
- Received date and time
- Folder location
- Microsoft-assigned email ID and web link

Attachments are not ingested as content. The `create_draft_email` tool can reference Unique-stored content via `unique://content/{contentId}` URIs, but this is separate from the sync pipeline.

Emails excluded by inbox filters (`ignoredBefore`, `ignoredSenders`, `ignoredContents`) are never ingested.

**See also:** [Inbox Filters](./technical/full-sync.md#inbox-filters)

## Security

### How are Microsoft tokens stored?

**Answer:** Microsoft access and refresh tokens are encrypted at rest using AES-256-GCM and stored in the `user_profiles` table. They are never sent to AI clients — the server issues separate opaque MCP bearer tokens for all client interactions.

**See also:** [Token Security](./technical/security.md#microsoft-tokens-encrypted-at-rest)

### How are MCP tokens stored?

**Answer:** MCP tokens are opaque 512-bit random values (`randomBytes(64)`). The full token value is stored directly in the `tokens` table and used for equality comparison during validation. Token unguessability is the security property — not one-way hashing.

**See also:** [MCP Tokens](./technical/security.md#mcp-tokens-opaque-bearer-tokens)

### Why does the server use PKCE?

**Answer:** PKCE (Proof Key for Code Exchange) prevents authorization code interception. Even if an attacker observes the redirect, they cannot exchange the authorization code without the code verifier that was generated client-side. PKCE is required by OAuth 2.1 for all authorization code flows.

**See also:** [OAuth 2.1 with PKCE](./technical/security.md#oauth-21-with-pkce)

### What happens if a refresh token is stolen?

**Answer:** The token family revocation mechanism detects reuse. Each refresh token has a `familyId`, `generation`, and `usedAt` timestamp. If a token is presented after it has already been used (indicating possible theft), the entire token family is revoked and the user must re-authenticate.

**See also:** [Refresh Token Rotation](./technical/security.md#refresh-token-rotation)

## Deployment

### Why is RabbitMQ required?

**Answer:** Microsoft requires webhook endpoints to respond within 10 seconds. Processing a live catch-up notification involves acquiring database locks, querying Microsoft Graph, and uploading emails to the knowledge base — which can take longer. RabbitMQ decouples receipt from processing: the webhook controller enqueues the notification and returns `202 Accepted` immediately, while the consumer processes it asynchronously.

**See also:** [Live Catch-Up](./technical/live-catchup.md) — [Architecture](./technical/architecture.md)

### What happens if RabbitMQ is unavailable?

**Answer:** Webhook notifications cannot be published to the queue. The webhook controller will fail to enqueue them and return an error to Microsoft. Microsoft will retry the notification. The server will resume processing once RabbitMQ is available and Microsoft retries, but notifications that exceed Microsoft's retry window may be lost.

Full sync is not affected by RabbitMQ availability — it pulls directly from Microsoft Graph.

### What happens if PostgreSQL is unavailable?

**Answer:** All operations that require database access will fail: inbox lock acquisition (blocking live catch-up and full sync), token validation (blocking all tool calls), and sync state updates. The service will resume once PostgreSQL is restored.

### Can one deployment serve multiple Microsoft tenants?

**Answer:** Yes. Configure the Entra ID app registration with "Accounts in any organizational directory" (multi-tenant). When each organization's admin grants consent, Microsoft creates an Enterprise Application in their tenant referencing your app registration. One deployment serves all tenants.

**See also:** [Architecture](./technical/architecture.md)

## Disaster Recovery

### What do I do if a core infrastructure component fails?

**Answer:** Recovery depends on which component was lost:

- **Local PostgreSQL DB loss** — all stored OAuth tokens and sync state are gone; every user must re-authenticate via `reconnect_inbox`.
- **RabbitMQ loss** — both in-progress full syncs and live catch-up are stalled; no re-authentication is needed. Live catch-up resumes automatically once RabbitMQ is restored; stalled full syncs require `restart_full_sync` per affected user.
- **Unique Knowledge Base loss** — ingested email content must be re-ingested; trigger `restart_full_sync` for each affected user. No re-authentication is needed.

**See also:** [Disaster Recovery Runbook](./operator/disaster-recovery.md)

## Related Documentation

- [Architecture](./technical/architecture.md) — System components and module descriptions
- [Flows](./technical/flows.md) — Sequence diagrams for all major flows
- [Permissions](./technical/permissions.md) — Required scopes and least-privilege justification
- [Security](./technical/security.md) — Encryption, PKCE, token rotation, and threat model
- [Tools](./technical/tools.md) — Full reference for all MCP tools
- [Full Sync](./technical/full-sync.md) — Historical batch ingestion mechanics
- [Live Catch-Up](./technical/live-catchup.md) — Webhook-driven real-time ingestion
- [Subscription Management](./technical/subscription-management.md) — Subscription lifecycle
- [Directory Sync](./technical/directory-sync.md) — Folder sync and delete detection
- [Operator Guide](./operator/README.md) — Deployment and operations
