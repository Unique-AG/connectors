# Design: Email Sync Command

**Ticket:** UN-16554

## Problem

The subscription infrastructure receives `created`, `updated`, and `deleted` webhook notifications from Microsoft Graph for user mailbox messages, but all notifications are currently discarded (TODO in the notification handler). We need a sync command that processes these notifications to keep the Unique knowledge base in sync with the user's Outlook mailbox.

## Solution

### Overview

Implement a unified `EmailSyncService` with a single public method `syncEmail(resource, subscriptionId)` that handles all three change types. The method fetches the email from Microsoft Graph, checks its parent folder, and determines the correct action: create, update, or delete from the Unique knowledge base.

The sync is self-healing and idempotent: it always converges to the correct KB state regardless of which notification triggered it, handling cases where notifications were missed.

### Architecture

#### New Components

1. **`EmailSyncService`** (`src/email-sync/sync/email-sync.service.ts`) -- Core sync engine with one public method:
   - `syncEmail(resource: string, subscriptionId: string): Promise<void>`

2. **`synced_emails` DB table** (`src/drizzle/schema/email-sync/synced-emails.table.ts`) -- Tracks ingested emails:
   - `id`: Primary key (typeid)
   - `emailId`: Immutable email ID from Microsoft Graph (unique)
   - `internetMessageId`: RFC 2822 Message-ID
   - `contentHash`: Hash of from+subject+uniqueBody for change detection
   - `scopeId`: Unique KB scope ID
   - `contentKey`: Key used in Unique `upsertContent`
   - `userProfileId`: FK to `user_profiles`
   - `createdAt`, `updatedAt`: Timestamps

3. **New DTOs** (`src/email-sync/sync/email-sync.dtos.ts`) -- Zod schemas for:
   - Graph API email response (selected fields)
   - Graph API mail folder response
   - Batch request/response (reuse existing from `subscription.dtos.ts`)

#### Modified Components

4. **`UniqueService`** -- Three new methods:
   - `ingestEmail(...)`: Creates/updates email content (scope creation, access setup, two-step upsert + .eml upload)
   - `deleteContent(key, scopeId)`: Removes content by key
   - `findContentByKey(key, scopeId)`: Checks if content exists in KB

5. **`MailSubscriptionController`** -- Updated notification handler to publish AMQP events for all three change types; new AMQP consumer for `unique.outlook-semantic-mcp.mail.change-notification.*` that routes to `EmailSyncService.syncEmail()`

6. **`SubscriptionModule`** -- Register new `EmailSyncService` and import dependencies

### Sync Flow

```
syncEmail(resource, subscriptionId)
  |
  +--> DB: subscriptionId -> userProfileId -> providerUserId
  |
  +--> Parse resource: extract messageId from "users/{id}/messages/{messageId}"
  |
  +--> Graph batch request:
  |      GET /users/{providerUserId}/messages/{messageId}?$select=...
  |      GET /users/{providerUserId}/mailFolders/deleteditems?$select=id
  |
  +--> Email fetch returned 404?
  |      YES --> Delete from KB (lookup key in synced_emails cache) --> DONE
  |
  +--> email.parentFolderId === deletedItemsFolder.id?
  |      YES --> Delete from KB --> Remove from synced_emails cache --> DONE
  |
  +--> Find content by key in Unique KB (findContentByKey)
  |
  +--> Content exists in KB?
  |      NO  --> Create: ingestEmail (upload .eml + metadata) --> Add to synced_emails
  |      YES --> Update metadata (folderPath, etc.)
  |              isDraft? --> Re-upload .eml (reingest)
  |              Not draft? --> Skip file upload
  |              Update synced_emails cache
```

### Graph API Calls

All calls use explicit `providerUserId` paths (not `/me/`):

- **Batch request** (`POST /$batch`):
  - `GET /users/{providerUserId}/messages/{messageId}?$select=id,subject,from,toRecipients,ccRecipients,receivedDateTime,parentFolderId,conversationId,conversationIndex,hasAttachments,isDraft,importance` with `Prefer: IdType="ImmutableId"`
  - `GET /users/{providerUserId}/mailFolders/deleteditems?$select=id`
- **Download .eml** (only when creating or reingesting draft):
  - `GET /users/{providerUserId}/messages/{messageId}/$value` returns MIME content (`message/rfc822`)

### Unique KB Integration

- **Scope structure**: `/{rootScopePath}/{userEmail}/email`
- **Access**: Owner gets WRITE + READ + MANAGE
- **Content key**: Immutable email ID from Microsoft Graph
- **MIME type**: `message/rfc822` for .eml files
- **Metadata fields**: `subject`, `from`, `to`, `cc`, `date`, `folderPath`, `conversationId`, `conversationIndex`, `hasAttachments`, `isDraft`, `importance`
- **Ingestion**: Two-step flow (upsert → upload to writeUrl → upsert with readUrl)
- **Content existence check**: `findContentByKey(key, scopeId)` via Unique API

### Error Handling

- **Graph API 404**: Email permanently deleted → delete from KB (not an error)
- **Graph API 401/403**: Token refresh handled by existing `TokenRefreshMiddleware`; if still fails, NACK for retry
- **Graph API 429**: Existing `RetryHandler` middleware handles throttling backoff
- **Graph API 5xx / network errors**: NACK to dead letter queue for retry
- **Unique API failures**: Assert and throw → NACK
- **Batch partial failure**: Retry entire sync
- **DB lookup failure**: Log and NACK

All operations are idempotent: re-running sync converges to correct state.

### Testing Strategy

Behavioral tests using `@suites/unit` TestBed:

**`EmailSyncService` tests:**
- Sync with email in normal folder (not in KB) → .eml download, content upsert, cache creation
- Sync with email in normal folder (in KB, non-draft) → metadata-only update
- Sync with email in normal folder (in KB, draft) → .eml re-upload and reingest
- Sync with email in Deleted Items → content deletion and cache removal
- Sync when Graph returns 404 → deletion path
- Sync when subscription not found → error handling
- Batch request construction with correct `providerUserId` paths

**`UniqueService` extension tests:**
- `ingestEmail`: scope creation, access setup, two-step upsert
- `deleteContent`: API call with correct key/scope
- `findContentByKey`: found vs not found

**Controller tests:**
- AMQP event publishing for all three change types
- Consumer routing to `EmailSyncService`

## Out of Scope

- Full folder path hierarchy (only immediate parent folder displayName for now)
- Email attachment ingestion
- Full mailbox initial sync (only webhook-driven incremental sync)
- Conversation threading in KB
- Email body text extraction (only .eml file ingestion)
- Retry/backoff strategy beyond what RabbitMQ provides

## Tasks

1. **Create `synced_emails` DB table and migration** -- Add Drizzle schema for tracking ingested emails with emailId, internetMessageId, contentHash, scopeId, contentKey, userProfileId. Generate and apply migration.

2. **Add Graph API email DTOs** -- Create Zod schemas for Graph email response (selected fields), mail folder response, and any batch-specific schemas needed beyond existing ones.

3. **Extend UniqueService with email methods** -- Add `ingestEmail(...)` for creating/updating email content with scope management, `deleteContent(key, scopeId)` for removal, and `findContentByKey(key, scopeId)` for existence checking. Follow existing two-step upsert pattern.

4. **Implement EmailSyncService** -- Create the core sync service with `syncEmail(resource, subscriptionId)` method. Includes DB lookups, Graph batch requests, parent folder check, KB create/update/delete logic, .eml download and upload, and synced_emails cache management.

5. **Wire notification handler and AMQP consumer** -- Update `MailSubscriptionController.notification()` to publish events for all three change types. Add AMQP consumer for `unique.outlook-semantic-mcp.mail.change-notification.*` that calls `EmailSyncService.syncEmail()`. Update `SubscriptionModule` with new providers.

6. **Write tests** -- Add behavioral tests for `EmailSyncService` (all sync scenarios), `UniqueService` extensions, and controller notification publishing/consuming.
