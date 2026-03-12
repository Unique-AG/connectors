# Design: Sync Redesign — Split Full Sync & Live Catch-up

## Problem

The current full sync is monolithic: it fetches all emails, performs a file diff against Unique, then queues changes. This has several issues:

- File diff is expensive and unnecessary — ingestion already checks `lastModifiedDateTime` to skip unchanged emails
- No resume capability — if the server restarts mid-sync, it starts over from scratch
- Live notifications are processed individually, not coordinated with the sync watermarks
- No clean separation between historical backfill and real-time updates

## Solution

### Overview

Split sync into two independent processes sharing a common set of date watermarks on `inbox_configuration`:

1. **Full Sync (historical backfill)** — walks emails from `newestLastModifiedDateTime` downward to `ignoredBefore` by `lastModifiedDateTime`, batching 200 at a time. Resumable on restart via `oldestCreatedDateTime`. No file diff. Schedules everything for ingestion at low priority.

2. **Live Catch-up (real-time)** — triggered by each incoming notification. Fetches all emails with `lastModifiedDateTime >= newestLastModifiedDateTime` from Microsoft, updates the upper watermark, and schedules for ingestion at high priority. Has its own lock independent of full sync.

**Shared state** (on `inbox_configuration`):

- `newestCreatedDateTime` / `oldestCreatedDateTime` — synced window shown to user
- `newestLastModifiedDateTime` / `oldestLastModifiedDateTime` — watermarks for sync coordination
- All updated via SQL `MIN`/`MAX`, reset to `NULL` on fresh full sync start

### Architecture

#### State Machine

**Full sync states:**
- `ready` → `fetching-emails` → `ready`
- Any → `failed`

States `performing-file-diff` and `processing-file-diff-changes` are dropped — no longer needed.

**Live catch-up states (new):**
- `ready` → `running` → `ready`
- Any → `failed`

Both stored on `inbox_configuration`. Independent locks — both can be active simultaneously.

#### Full Sync Flow

1. Acquire lock (existing `SELECT FOR UPDATE` pattern)
2. If fresh start (no `oldestCreatedDateTime`): set `newestLastModifiedDateTime` to current time if not already set by live catch-up
3. If resuming: continue from `oldestCreatedDateTime`
4. Fetch 200 emails from Microsoft: `createdDateTime gt {ignoredBefore}`, ordered by `lastModifiedDateTime desc`, starting from current position
5. For each batch:
   - Schedule all emails for ingestion (low priority AMQP)
   - Update stats via `MIN`/`MAX` SQL on the four date columns
6. When no more emails or `createdDateTime <= ignoredBefore`: mark complete, set state to `ready`

#### Live Catch-up Flow

1. Notification arrives → attempt to acquire live catch-up lock (separate from full sync lock)
2. If lock acquired:
   - Read `newestLastModifiedDateTime` as watermark
   - Fetch all emails with `lastModifiedDateTime >= watermark` from Microsoft (paginated, 200 per page)
   - Schedule all for ingestion (high priority AMQP)
   - Update stats via `MIN`/`MAX` SQL
   - Release lock
3. If lock not acquired: do nothing — the running catch-up covers it via the watermark query

No in-memory buffers, no debouncing, no individual message ID tracking.

#### Restart / Recovery

- **Full sync resume**: on startup, if `fullSyncState === 'fetching-emails'`, resume from `oldestCreatedDateTime` downward — no progress lost
- **Live catch-up**: on startup, run one catch-up from `newestLastModifiedDateTime` to pick up anything missed while down
- **Stuck sync recovery**: existing 15-minute cron still applies, resets state to `ready`

#### Coordination Between Processes

- Live catch-up owns the upper frontier (`newestLastModifiedDateTime` → future)
- Full sync walks downward from `newestLastModifiedDateTime` to `ignoredBefore`
- If live catch-up runs before full sync starts, it establishes the watermark; full sync then starts downward from there
- If full sync starts first with no watermark, it sets `newestLastModifiedDateTime` to "now"
- No overlap between the two processes

### Error Handling

**Full sync errors:**
- Microsoft API failure mid-batch: set state to `failed`. Recovery cron picks it up after 15 minutes and resumes from `oldestCreatedDateTime` — no progress lost.
- Lock contention: skip, another full sync is already running.

**Live catch-up errors:**
- Microsoft API failure: set state to `failed`. Next notification triggers a retry naturally.
- Lock contention: skip, running catch-up covers it.
- Full sync not yet started (no watermark): skip live catch-up — no `newestLastModifiedDateTime` to query from. Full sync must run first to establish the watermark.

**Ingestion errors:**
- Unchanged — ingestion already handles retries via dead-letter queue and `lastModifiedDateTime` dedup.

### Testing Strategy

Behavioral tests using existing vitest setup with mocked Microsoft Graph API and real database transactions:

- Full sync: verify it walks batches downward, updates date stats via min/max, resumes from `oldestCreatedDateTime` on restart, stops at `ignoredBefore`
- Live catch-up: verify it fetches from watermark, updates upper stats, skips when lock is held, skips when no watermark exists
- Concurrency: verify full sync and live catch-up can run simultaneously, but two full syncs or two live catch-ups cannot

## Out of Scope

- File diff removal cleanup — removing the Unique API file diff integration entirely (follow-up)
- Subscription webhook changes — the webhook endpoint stays the same, just the downstream handler changes
- Filter changes — `ignoredBefore`, `ignoredSenders`, `ignoredContents` stay as-is
- Progress percentage calculation — dropping counters means the current formula no longer applies; UI changes to show date windows instead are out of scope
- AMQP queue/exchange changes — same queues, just different event routing

## Tasks

1. **Update database schema** — Add `liveCatchUpState` enum and column to `inbox_configuration`. Replace counter columns (`messagesFromMicrosoft`, `messagesQueuedForSync`, `messagesProcessed`) with four date watermark columns (`newestCreatedDateTime`, `oldestCreatedDateTime`, `newestLastModifiedDateTime`, `oldestLastModifiedDateTime`). Update `fullSyncState` enum to use `ready` instead of `full-sync-finished` and drop `performing-file-diff`/`processing-file-diff-changes`.

2. **Rewrite full sync command** — Remove file diff step. Fetch emails in batches of 200 ordered by `lastModifiedDateTime desc`, starting from `newestLastModifiedDateTime` (or now) downward to `ignoredBefore`. Update date watermarks via SQL `MIN`/`MAX` per batch. Schedule all emails for ingestion at low priority. Support resume from `oldestCreatedDateTime` on restart.

3. **Implement live catch-up command** — New command triggered by notifications. Acquires its own lock (independent from full sync). Fetches all emails with `lastModifiedDateTime >= newestLastModifiedDateTime` from Microsoft, paginated at 200. Updates watermarks via SQL `MIN`/`MAX`. Schedules for ingestion at high priority. Skips if no watermark exists yet.

4. **Update notification handler** — Replace per-notification individual ingestion (`IngestEmailViaSubscriptionCommand`) with triggering the live catch-up process. Each notification attempts the catch-up; if lock is held, it's a no-op.

5. **Update stats query and state machine** — Rewrite `GetFullSyncStatsQuery` to return date windows instead of counters. Update state enums and transitions for both full sync and live catch-up. Update recovery service to handle both states.

6. **Write tests** — Behavioral tests for full sync batching/resume, live catch-up watermark fetch/lock, concurrency between the two processes, and restart recovery.
