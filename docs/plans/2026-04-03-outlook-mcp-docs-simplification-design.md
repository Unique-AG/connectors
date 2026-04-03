# Design: Outlook MCP Docs Simplification

## Problem

The technical docs contain 4 files (`full-sync.md`, `live-catchup.md`, `directory-sync.md`, `subscription-management.md`) that document internal implementation details — state machines, batching mechanics, recovery thresholds, sequence diagrams — at a depth more appropriate for code comments than operator/architect docs. They create cross-reference clutter across `faq.md`, `flows.md`, and `technical/README.md`. Some of those cross-references also point to content that is now stale (the live catch-up buffering logic was removed in migration `0024_petite_masque.sql`).

## Solution

### Overview

Remove the 4 detailed process files. Expand the existing `### Sync Pipeline` subsection in `architecture.md` with one short paragraph per process. Simplify `flows.md` by removing the "see detailed file" forward references and leaving the existing key-points bullets. Fix all broken cross-references in `faq.md` and correct the two stale FAQ answers that describe buffering behavior that no longer exists. Update `technical/README.md` to remove the 4 deleted file entries.

### Architecture

**`architecture.md` — expand `### Sync Pipeline`**

Replace the current 3-bullet list with four short paragraphs:

- **Full Sync** — triggered automatically after connection; fetches historical emails in paginated batches (newest first); applies `DEFAULT_MAIL_FILTERS`; resumable via persisted Graph cursor; initializes the watermark live catch-up depends on.
- **Live Catch-Up** — webhook-driven; acknowledged immediately via RabbitMQ, processed async in the consumer; queries Graph for messages since the watermark; watermark defaults to `now()` on inbox creation so notifications are never buffered.
- **Directory Sync** — runs on a 5-minute delta query schedule; keeps local folder tree in sync with Outlook; powers `list_folders` and folder-based search filtering; detects email deletion by tracking moves to excluded folders (e.g. Deleted Items).
- **Subscription Management** — Graph webhook subscription created automatically on connect; renewed via Microsoft lifecycle notifications (`reauthorizationRequired`); if `subscriptionRemoved`, user calls `reconnect_inbox`; `verify_inbox_connection` reports status (`active`, `expiring_soon`, `expired`, `not_configured`).

Remove cross-reference links to the 4 deleted files. Add a reference to `flows.md` for sequence diagrams.

**`flows.md` — remove forward references**

- Live Catch-Up, Full Sync, Directory Sync sections: delete the `"For the detailed sequence diagram and full technical description, see [X]"` sentence from each. Key-points bullets stay unchanged.
- Subscription Creation section: the inline `"Subscription states: See [Subscription Management — Subscription Status](./subscription-management.md#...)"` note is replaced with the 4-row status table inline.
- Related Documentation footer: remove the 4 deleted file entries.

**`faq.md` — fix links and correct stale content**

Cross-reference fixes in the Sync section (replace with `[Architecture — Sync Pipeline](./technical/architecture.md#Sync-Pipeline)` or `[Flows](./technical/flows.md)` as appropriate):
- "What is the difference between full sync and live catch-up?" — remove link to `full-sync.md#Sync-States`
- "Why is my full sync stuck in `waiting-for-ingestion`?" — remove link to `full-sync.md#Stale-Sync-Recovery`
- "Why is my full sync stuck in `running`?" — remove link to `full-sync.md#Stale-Sync-Recovery`
- "What happens if full sync is interrupted?" — remove link to `full-sync.md#How-Batching-Works`
- "Why are new emails not appearing in search results?" — remove links to `live-catchup.md` and `subscription-management.md`
- "What happens to emails sent during full sync?" — remove links to `full-sync.md` and `live-catchup.md`
- "Why are deleted emails still appearing in search results?" — remove links to `directory-sync.md` and `live-catchup.md`

Stale content corrections:
- "What happens to emails sent during full sync?" — remove the sentence about buffering ("Notifications received before that point are buffered and flushed once ready"). Replace with: live catch-up processes notifications immediately since the watermark is always initialized on inbox creation.
- "Why are new emails not appearing in search results?" — remove item 4 ("Watermarks not initialized — if full sync has not yet initialized the watermarks, live catch-up buffers incoming notifications...") entirely.

Related Documentation footer: remove the 4 deleted file entries.

**`technical/README.md` — remove 4 table rows** for Full Sync, Live Catch-Up, Subscription Management, Directory Sync.

**Delete** `full-sync.md`, `live-catchup.md`, `directory-sync.md`, `subscription-management.md`.

### Error Handling

Not applicable — this is a documentation-only change.

### Testing Strategy

Not applicable — no code changes.

## Out of Scope

- Rewriting the content of `flows.md` sequence diagrams
- Changes to `security.md`, `permissions.md`, `tools.md`, or the operator docs
- Updating Confluence page IDs or sync metadata in the file headers

## Tasks

1. **Expand `### Sync Pipeline` in `architecture.md`** — Replace the 3-bullet summary with four short paragraphs (Full Sync, Live Catch-Up, Directory Sync, Subscription Management). Drop cross-reference links to deleted files; add a reference to `flows.md`.

2. **Simplify sync sections in `flows.md`** — Remove the "For the detailed sequence diagram..." sentence from Live Catch-Up, Full Sync, and Directory Sync sections. Inline the subscription status table in place of the `subscription-management.md` reference. Remove 4 entries from the Related Documentation footer.

3. **Fix `faq.md` cross-references and stale content** — Redirect broken `See also` links in the Sync section. Correct the two answers that describe buffering behavior that no longer exists. Remove 4 entries from the Related Documentation footer.

4. **Update `technical/README.md`** — Remove the 4 table rows for the deleted files.

5. **Delete the 4 detailed process files** — Remove `full-sync.md`, `live-catchup.md`, `directory-sync.md`, `subscription-management.md`.
