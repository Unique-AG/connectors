# Design: Full Sync Next Link Checkpoint & Live Catch-Up Message Buffering

## Problem

**Full sync resumability** — When a full sync fails mid-way and resumes, it re-fetches all pages from the beginning using watermark-based filtering. This wastes API calls and time for large mailboxes where many pages were already processed.

**Live catch-up message loss** — When a webhook notification arrives while a live catch-up is already running, the message IDs are silently dropped. If those IDs aren't picked up by the next live catch-up's Graph query (e.g., timing window), they're lost.

## Solution

### Overview

**Full Sync Next Link Checkpoint**: Add a `fullSyncNextLink` text column to `inboxConfiguration`. The fetch loop saves the `@odata.nextLink` after each successfully processed batch. On resume, the command detects the saved link and skips the initial API call, continuing pagination from where it left off. On fresh sync start or completion, the column is cleared. The existing watermark logic remains unchanged.

**Live Catch-Up Pending Message Buffer**: Add a `pendingLiveMessageIds` text array column to `inboxConfiguration`. When the command's `acquireLock` detects `liveCatchUpState === 'running'`, it appends the incoming message IDs to `pendingLiveMessageIds` and returns early. During batch processing, any message ID that exists in `pendingLiveMessageIds` is skipped (deferred to the end). Before releasing the lock at the end of a successful run, the command reads `pendingLiveMessageIds` in a transaction, filters out already-ingested IDs, publishes the rest to the queue, and clears the column.

### Architecture

#### Schema Changes

One new migration adding two columns to `inboxConfiguration`:
- `fullSyncNextLink: text, nullable, default null`
- `pendingLiveMessageIds: text[], not null, default '{}'`

#### Full Sync Changes (`execute-full-sync.command.ts`)

**`run()` method:**
- Pass `fullSyncNextLink` from the DB query to `fetchAndScheduleBatches`.

**`fetchAndScheduleBatches()`:**
- New parameter: `nextLink: string | null`
- If `nextLink` is present: skip the initial API call, fetch directly from the saved link.
- If `nextLink` is null: build filter expression and make initial call as today.
- After each `processBatch` + `updateWatermarks`: also save `@odata.nextLink` to DB.
- On loop completion: clear `fullSyncNextLink`.

**`start-full-sync.command.ts`:**
- Fresh sync: set `fullSyncNextLink` to null (part of the reset).
- Resume: keep the existing `fullSyncNextLink` value.

#### Live Catch-Up Changes (`live-catch-up.command.ts`)

**`acquireLock()`:**
- When `liveCatchUpState === 'running'` and there are incoming `messageIds`: append to `pendingLiveMessageIds` via SQL `array_cat`, then return skip.
- When `liveCatchUpState === 'running'` and no `messageIds`: return skip as today.

**`processBatch()`:**
- Accept `pendingLiveMessageIds` set.
- Skip publishing any message ID that's in the pending set.

**New method `flushPendingMessages()`:**
- Called at end of run, before setting state to `ready`.
- In a transaction: read `pendingLiveMessageIds`, filter out already-ingested, publish rest, clear column, set state to `ready`.

### Error Handling

**Full Sync Next Link:**
- Failure during batch processing: `fullSyncNextLink` in DB still points to the last successfully saved link. On resume, it picks up from there.
- Stale/expired next link on resume: If the resume call using the saved link returns an error, fall back to fresh fetch — clear the next link and proceed with watermark-based filtering.

**Live Catch-Up Buffering:**
- Failure during live catch-up: `pendingLiveMessageIds` stays in DB. Next successful run will flush them.
- Failure during `flushPendingMessages()`: Transactional — either all get published and cleared, or none do. IDs remain buffered for the next run.

### Testing Strategy

**Full Sync Next Link:**
- When `fullSyncNextLink` is present, fetch loop skips initial call and starts from saved link.
- After each batch, next link is persisted to DB.
- On completion, next link is cleared.
- When saved next link fails (expired), falls back to fresh fetch with filters.
- Fresh sync clears any existing next link.

**Live Catch-Up Buffering:**
- When `liveCatchUpState === 'running'` and messageIds provided, they get appended to `pendingLiveMessageIds` and command returns early.
- Batch processing skips message IDs present in `pendingLiveMessageIds`.
- `flushPendingMessages` publishes buffered IDs not already ingested and clears the column.
- Flush + state update is transactional.
- When no pending IDs exist, flush is a no-op.

Use existing test setup (Drizzle + mocked Graph client + mocked AMQP).

## Out of Scope

- Changing the fetch endpoint from `/me/messages` to `/me/messages/delta`.
- Deduplication of message IDs beyond checking the ingestion table.
- Retry logic for individual failed message publishes.
- Changes to the stuck sync recovery service.

## Tasks

1. **Add schema migration** - Add `fullSyncNextLink` (text, nullable) and `pendingLiveMessageIds` (text[], default '{}') columns to `inboxConfiguration`. Update the Drizzle schema TypeScript definition.

2. **Implement next link checkpoint in full sync** - Modify `fetchAndScheduleBatches` to accept and use a saved next link on resume. After each batch + watermark update, persist the current `@odata.nextLink` to DB. Clear on completion. Update `start-full-sync.command.ts` to clear the next link on fresh sync.

3. **Implement expired next link fallback** - When fetching from a saved next link fails, catch the error, clear the stored link, and fall back to fresh fetch with filter expression.

4. **Implement message buffering in live catch-up** - Modify `acquireLock` to append incoming messageIds to `pendingLiveMessageIds` when state is `running`. Modify batch processing to skip IDs in the pending set.

5. **Implement flush pending messages** - Add `flushPendingMessages` method that reads `pendingLiveMessageIds` in a transaction, filters out already-ingested IDs, publishes the rest, clears the column, and sets state to `ready`.

6. **Add tests for next link checkpoint** - Test resume from saved link, persistence after batch, clearing on completion, and expired link fallback.

7. **Add tests for live catch-up buffering** - Test buffering on running state, batch dedup against pending set, flush publishing, transactional behavior, and no-op when empty.
