<!-- confluence-page-id: 2062942216 -->
<!-- confluence-space-key: PUBDOC -->

# Flows

This page documents the key flows in the Outlook Semantic MCP Server: how users connect, how emails are synced in real time and historically, how subscriptions stay alive, and how email drafts are created.

## User OAuth Connection Flow

When a user opens their MCP client and connects to the Outlook Semantic MCP Server for the first time, the following flow executes:

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    actor User
    participant MCPClient as MCP Client
    participant OutlookMCP as Outlook Semantic MCP Server
    participant EntraID as Microsoft Entra ID
    participant DB as PostgreSQL
    participant AMQP as RabbitMQ

    User->>MCPClient: Connect to MCP server
    MCPClient->>OutlookMCP: GET /mcp
    OutlookMCP->>MCPClient: 401 with authorization server metadata
    MCPClient->>EntraID: OAuth 2.1 authorization request (PKCE)
    EntraID->>User: Show Microsoft consent screen
    User->>EntraID: Grant permissions
    EntraID->>OutlookMCP: Redirect with authorization code
    OutlookMCP->>EntraID: Exchange code for Microsoft tokens
    EntraID->>OutlookMCP: Access token + refresh token
    OutlookMCP->>DB: Encrypt and store Microsoft tokens in user_profiles
    OutlookMCP->>DB: Store MCP token in tokens table
    OutlookMCP->>AMQP: Publish user-authorized event
    OutlookMCP->>MCPClient: Issue opaque MCP bearer token
```

After the `user-authorized` event is published, the server automatically creates a Microsoft Graph webhook subscription and starts a full email sync — no further user action is needed.

**Key points:**

- Microsoft tokens (access + refresh) are encrypted at rest using AES-256-GCM and **never** exposed to the MCP client.
- The MCP client receives a separate, short-lived MCP bearer token for all subsequent tool calls.
- The PKCE code verifier prevents authorization code interception even if the redirect is observed.

## Microsoft Token Refresh Flow

Microsoft access tokens expire after approximately one hour. The server refreshes them transparently:

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    participant OutlookMCP as Outlook Semantic MCP Server
    participant Middleware as Token Refresh Middleware
    participant MSGraph as Microsoft Graph API
    participant EntraID as Microsoft Entra ID
    participant DB as PostgreSQL

    OutlookMCP->>MSGraph: API call with access token
    MSGraph->>Middleware: 401 InvalidAuthenticationToken
    Middleware->>DB: Fetch encrypted refresh token from user_profiles
    Middleware->>EntraID: POST /oauth2/v2.0/token (grant_type=refresh_token)
    EntraID->>Middleware: New access token (+ possibly new refresh token)
    Middleware->>DB: Update encrypted tokens in user_profiles
    Middleware->>MSGraph: Retry original request with new access token
    MSGraph->>OutlookMCP: Successful response
```

**Key points:**

- Refresh is automatic — no user intervention required.
- If the refresh token itself is expired (~90 days of inactivity), the user must reconnect via `reconnect_inbox`.
- The server stores the new refresh token if Microsoft rotates it; otherwise the existing refresh token is kept.

## Subscription Creation and Renewal Lifecycle

Microsoft Graph webhook subscriptions for messages can last up to 7 days (Microsoft limit). The service creates subscriptions that renew daily at the configured UTC hour. The server manages the full lifecycle:

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    participant AMQP as RabbitMQ
    participant OutlookMCP as Outlook Semantic MCP Server
    participant MSGraph as Microsoft Graph API
    participant DB as PostgreSQL

    Note over AMQP,DB: Triggered by user-authorized event
    AMQP->>OutlookMCP: user-authorized (userProfileId)
    OutlookMCP->>DB: Check for existing subscription
    alt No subscription or expired
        OutlookMCP->>MSGraph: POST /subscriptions (resource: users/{id}/messages)
        MSGraph->>OutlookMCP: Subscription ID + expiration
        OutlookMCP->>DB: Store subscription record
        OutlookMCP->>AMQP: Publish subscription-created event
    else Subscription still valid
        OutlookMCP->>OutlookMCP: Skip (already active)
    end

    Note over AMQP,DB: Before expiry — lifecycle notification from Microsoft
    MSGraph->>OutlookMCP: POST /mail-subscription/lifecycle (reauthorizationRequired)
    OutlookMCP->>OutlookMCP: Validate clientState secret
    OutlookMCP->>MSGraph: PATCH /subscriptions/{id} (new expirationDateTime)
    MSGraph->>OutlookMCP: Updated subscription
    OutlookMCP->>DB: Update subscription expiresAt

    Note over AMQP,DB: Subscription removed by Microsoft
    MSGraph->>OutlookMCP: POST /mail-subscription/lifecycle (subscriptionRemoved)
    OutlookMCP->>OutlookMCP: Validate clientState secret
    OutlookMCP->>DB: Delete subscription and inbox_configurations records
```

**Subscription states:** See [Subscription Management — Subscription Status](./subscription-management.md#Subscription-Status) for the full status reference.

**Key points:**

- Microsoft sends lifecycle notifications before a subscription expires (`reauthorizationRequired`) and when it removes one (`subscriptionRemoved`).
- All lifecycle notifications are validated against the `MICROSOFT_WEBHOOK_SECRET` via the `clientState` field.
- `reconnect_inbox` is idempotent: it creates a new subscription only if none exists or the existing one has expired. If the subscription is `already_active` or `expiring_soon`, no changes are made.

## Live Catch-Up: Webhook-Driven Email Ingestion

When a new email arrives in the user's Outlook mailbox, Microsoft Graph sends a webhook notification. The server enqueues the notification in RabbitMQ and returns `202 Accepted` immediately. The consumer then fetches and ingests new messages inline within the same execution.

For the detailed sequence diagram and full technical description, see [Live Catch-Up](./live-catchup.md).

**Key points:**

- Microsoft requires a response within 10 seconds (Microsoft limit, not configurable). The server enqueues the notification immediately and returns `202 Accepted` — actual email fetching and ingestion happen inline in the consumer, after the webhook response is already sent.
- Buffering applies when another live catch-up consumer is already processing, or when the watermark has not been set yet (full sync has not started). Messages are flushed once the blocker clears.
- The watermark (`newestLastModifiedDateTime`) is **initialized by full sync** the first time it runs and **maintained by live catch-up** on every subsequent notification.
- `deleted` change notifications are discarded. Deletions are handled by [directory sync](./directory-sync.md) and by detecting emails moved to ignored folders.

## Full Sync: Historical Email Ingestion

After a subscription is created, the server automatically begins ingesting the user's historical emails. It fetches messages from Microsoft Graph in paginated batches (newest first), applies the configured mail filters, and uploads them to the Unique Knowledge Base. The sync is resumable across restarts and initializes the watermark that live catch-up depends on.

For the detailed sequence diagram and full technical description, see [Full Sync](./full-sync.md).

**Key points:**

- Full sync is triggered automatically when a subscription is created — users do not need to invoke it manually.
- The sync is resumable: the Graph pagination cursor is persisted so a crash or restart picks up where it left off.
- Stale syncs (no heartbeat for 20+ minutes) are automatically restarted by the sync recovery module.
- `ignoredBefore` is applied as a Graph API query filter. `ignoredSenders` and `ignoredContents` are applied in-memory after each batch is fetched.
- Full sync **initializes** the watermark (`newestLastModifiedDateTime`). Once initialized, live catch-up takes ownership and updates it on every subsequent notification.

## Directory Sync Flow

The server continuously syncs the user's Outlook folder structure from Microsoft Graph. This serves two purposes: enabling folder-based search filtering via the `list_folders` tool, and tracking email movement between folders to handle "deleted" emails without relying on delete notifications.

For the detailed sequence diagram and full technical description, see [Directory Sync](./directory-sync.md).

**Key points:**

- Directory sync runs on a 5-minute schedule using Graph delta queries, plus on-demand at the start of each full sync and live catch-up execution.
- Folders such as Deleted Items and Junk Email are excluded from sync (`ignoreForSync = true`). When an email is moved to an excluded folder, it is removed from the knowledge base.
- The `list_folders` tool returns the folder tree synced here. The folder IDs it returns can be passed in the `conditions[].directories` field of `search_emails` to narrow results to a specific mailbox folder.

## Email Draft Creation Flow

When the user calls the `create_draft_email` tool:

```mermaid
%%{init: {'theme': 'neutral', 'themeVariables': { 'fontSize': '14px' }}}%%
sequenceDiagram
    autonumber
    participant MCPClient as MCP Client
    participant OutlookMCP as Outlook Semantic MCP Server
    participant MSGraph as Microsoft Graph API

    MCPClient->>OutlookMCP: create_draft_email (subject, body, recipients, attachments)
    OutlookMCP->>MSGraph: POST /me/messages (subject, body, toRecipients, ccRecipients)
    MSGraph->>OutlookMCP: Draft created (draftId, webLink)

    opt Attachments provided
        loop For each attachment
            OutlookMCP->>MSGraph: POST /me/messages/{draftId}/attachments
            MSGraph->>OutlookMCP: Attachment added
        end
    end

    OutlookMCP->>MCPClient: Return draftId, webLink, attachmentsFailed[]
```

**Key points:**

- The draft is created in the user's Outlook Drafts folder via Microsoft Graph — it is **not** sent automatically.
- The `webLink` in the response lets the user open the draft directly in Outlook to review and send.
- If one or more attachments fail to upload, the draft is still returned with a list of failed attachments.

## Related Documentation

- [Architecture](./architecture.md) - System components and module descriptions
- [Full Sync](./full-sync.md) - Full sync mechanics, states, and filters in detail
- [Live Catch-Up](./live-catchup.md) - Webhook-driven sync, subscription lifecycle, and directory sync in detail
- [Security](./security.md) - Token encryption, PKCE, and token rotation
