# PR Proposal

## Ticket
UN-16554

## Title
feat(outlook-semantic-mcp): implement email sync command for webhook notifications

## Description
- Add unified `EmailSyncService.syncEmail()` that processes created/updated/deleted webhook notifications from Microsoft Graph to keep Unique KB in sync with Outlook mailbox
- Extend `UniqueService` with `ingestEmail`, `deleteContent`, and `findContentByKey` methods for email-specific KB operations
- Add `synced_emails` DB table to track ingested emails with immutable IDs, content hashes, and scope references for self-healing sync
- Wire `MailSubscriptionController` notification handler to publish AMQP events for all change types and add consumer that routes to sync service
- Use Graph batch requests with explicit `providerUserId` paths for efficient email + deleted items folder fetching
