# Design: Full Sync Pausable & Fair to All Users

## Problem

A single user's full sync (up to 60k messages) floods the shared RabbitMQ ingestion queue, blocking live catchup for all users. The current priority mechanism (Low for full sync, High for live catchup) is insufficient — live catchup messages still wait behind tens of thousands of queued full sync messages. Live catchup should always run regardless of what full sync does.

## Solution

### Overview

Decouple full sync from the shared RabbitMQ queue entirely. Full sync becomes a cron-driven, self-throttling loop that calls the ingestion API directly in short bursts — upload up to 100 messages, park in `waiting-for-ingestion`, and let a cron job wake it up when the pipeline has drained. This ensures full sync never competes with live catchup on the queue.

The sync is pausable/resumable via MCP tools, tracks granular progress counters, and is fully resumable down to the individual message index within a Graph API page.

Live catchup keeps using RabbitMQ (now uncontested). Priority config is removed since there's no competition.

### State Machine

```
ready (idle) ──→ running ◄──────────────────┐
                  │    │                     │
                  │    ▼                     │
                  │  waiting-for-ingestion ──┤
                  │    │                     │
                  ▼    ▼                     │
               paused ─┼──→ running          │
                  │    │──→ waiting-for-ingestion
                  │    └──→ ready
                  │                          │
               failed ──(cron)───────────────┘
```

**States:**
- `ready` — idle, no sync in progress. Clean slate for a fresh start.
- `running` — actively fetching from Graph API and calling ingestion.
- `waiting-for-ingestion` — uploaded a batch of up to 100 messages, waiting for the pipeline to drain below 20 in-progress.
- `paused` — user paused the sync. Current batch finishes, then stops. Cron skips paused syncs entirely.
- `failed` — unrecoverable error. Cron recovers.

**Transitions:**
- `ready` → `running`: sync triggered by existing queue event or user tool call.
- `running` → `waiting-for-ingestion`: uploaded 100 files, parking until drain.
- `waiting-for-ingestion` → `running`: cron publishes retrigger event, execution logic checks 5-minute cooldown + <20 in-progress in scope stats.
- `running` / `waiting-for-ingestion` → `paused`: user calls pause tool.
- `paused` → `running` / `waiting-for-ingestion` / `ready`: user calls resume, sync loop re-enters decision logic to determine correct next state.
- `running` → `failed`: unrecoverable error.
- `failed` → `running`: cron recovery.
- `running` → early exit: version mismatch (restart from scratch was called).
- `running` → `ready`: all pages processed, sync complete.

**What starts a sync:**
- Existing trigger mechanism (queue event, like today)
- User calling the run full sync tool

**What keeps it moving (cron):**

The cron job is a pure trigger — it publishes retrigger events to a queue for all syncs that are not in `ready` or `paused` state. It does NOT check scope stats or any other conditions. All condition checking (scope stats, heartbeat age, cooldowns) happens inside the sync execution logic when it receives the event.

- `waiting-for-ingestion`: publish retrigger event
- `failed`: publish retrigger event
- `running`: publish retrigger event (execution logic checks if heartbeat >20 min to detect pod death)
- `paused`: skip
- `ready`: skip (cron never starts a fresh sync)

When the sync execution receives a retrigger event, it acquires the lock and applies the decision logic:
- `waiting-for-ingestion`: check 5-minute cooldown + scope stats <20 in-progress → resume or stay parked
- `running`: check heartbeat >20 min → recover or exit (already running)
- `failed`: resume from last checkpoint

### Sync Loop (Single Burst)

Each invocation does one unit of work then parks:

1. Acquire lock (DB transaction with `FOR UPDATE`)
2. Check version — exit early on mismatch
3. If first run, call `$count` API to populate `expectedTotal`
4. Fetch current Graph API page using saved `fullSyncNextLink`
5. Resume from saved `fullSyncBatchIndex` within the page
6. For each message (up to 100 per burst):
   - Call ingestion API directly (3 retries, exponential backoff)
   - On success: increment `scheduledForIngestion`, save batch index
   - On failure after retries: clean up registered content, increment `failedToUploadForIngestion`, continue
   - If message filtered: increment `skippedMessages`
   - Update heartbeat
   - Check version — exit early on mismatch
7. After 100 uploads → transition to `waiting-for-ingestion`, exit
8. If page exhausted → save nextLink, reset batch index to 0, continue to next page or complete

### Database Schema Changes

New columns on `inbox_configuration`:
- `full_sync_batch_index: integer default 0` — current position within a Graph API page
- `full_sync_expected_total: integer` — from `$count` API call at sync start
- `full_sync_skipped: integer default 0` — messages filtered out
- `full_sync_scheduled_for_ingestion: integer default 0` — successfully submitted
- `full_sync_failed_to_upload_for_ingestion: integer default 0` — failed after 3 retries

Enum expansion: `inboxSyncState` gains `paused` and `waiting-for-ingestion` values.

Existing columns retained: `fullSyncVersion`, `fullSyncNextLink`, `fullSyncHeartbeatAt`, `fullSyncLastRunAt`, `fullSyncLastStartedAt`, date window fields.

### Components Changed/Added

Replaces the current `StartFullSyncCommand` / `ExecuteFullSyncCommand` split with a more sensible separation:

1. **`full-sync.command.ts`** (new, replaces `StartFullSyncCommand` + `ExecuteFullSyncCommand`) — main entry point and orchestrator. Acquires lock, checks state and conditions (version mismatch, scope stats, pause, 5-minute cooldown), decides what to do next, delegates to batch service. Handles transitions between all states.
2. **`full-sync-batch.service.ts`** (new) — batch processing logic. Fetches Graph API page, iterates messages from saved index, calls ingestion API directly with 3 retries + exponential backoff, saves batch index and counters after each message, updates heartbeat.
3. **`full-sync-reset.service.ts`** (new) — restart from scratch logic. Generates new version, resets nextLink/index/counters, sets state to `ready`. Called by the restart tool.
4. **`FullSyncRecoveryService`** (new) — simple cron that publishes retrigger events to a queue for all syncs not in `ready` or `paused` state. No condition checking — just a trigger.
5. **`LiveCatchupRecoveryService`** (new) — extracted from current `StuckSyncRecoveryService`, handles live catchup recovery only.
6. **`StuckSyncRecoveryService`** — removed, replaced by the two above.
7. **Pause/Resume/Restart MCP tools** — 3 new tools. Pause flips state. Resume retriggers sync loop. Restart calls `full-sync-reset.service.ts`.
8. **`SyncProgressTool`** — updated to include counters (`expectedTotal`, `skippedMessages`, `scheduledForIngestion`, `failedToUploadForIngestion`) alongside existing date window and ingestion stats.
9. **Ingestion queue** — remove priority config. Full sync no longer publishes to it.
10. **`IngestionListener`** — remove `IngestFullSyncMessageCommand` handler. Queue is live-catchup-only.

### Restart from Scratch

When the user calls the restart tool:
1. Generate new `fullSyncVersion`
2. Reset `fullSyncNextLink` to `START_DELTA_LINK`
3. Reset `fullSyncBatchIndex` to 0
4. Reset all counters to 0
5. Set state to `ready`
6. Any currently running sync loop exits early at next version check

### Progress Tool Response

The sync progress tool returns:
- Current state (`ready`, `running`, `waiting-for-ingestion`, `paused`, `failed`)
- Counters: `expectedTotal`, `skippedMessages`, `scheduledForIngestion`, `failedToUploadForIngestion`
- Date window: `newestCreatedDateTime`, `oldestCreatedDateTime`, `newestLastModifiedDateTime`
- Ingestion stats from scope: `finished`, `inProgress`, `failed`
- Live catchup state

## Error Handling

1. **Ingestion call fails (3 retries exhausted):** Clean up registered content, increment `failedToUploadForIngestion`, continue to next message.
2. **Graph API page fetch fails:** Set state to `failed`, cron recovers. Batch index is saved so we resume from last processed message.
3. **Pod restart mid-batch:** Heartbeat goes stale, cron detects stuck >20 min, retriggers. Resumes from saved `fullSyncNextLink` + `fullSyncBatchIndex`.
4. **Version mismatch (restart from scratch):** Running loop exits early at next checkpoint, no cleanup needed.
5. **`$count` API call fails at start:** Proceed with `expectedTotal = null` — progress tool shows counts without percentage.

## Testing Strategy

1. **Unit tests for state transitions** — test the decision logic: given current state + conditions (scope stats, heartbeat age, version), assert correct next state.
2. **Unit tests for batch processing** — test the resume-from-index logic, counter increments, retry + cleanup on ingestion failure.
3. **Unit tests for pause/resume/restart tools** — test state flips and version regeneration.
4. **Unit tests for cron service** — test it correctly identifies which syncs to retrigger and skips paused/ready ones.

Use existing test setup. Focus on behavioral tests for the state machine and cron logic.

## Out of Scope

- Changing the live catchup mechanism (keep queue, just remove priority)
- Purging old documents from Unique scope on restart
- Rate limiting per user across multiple pods
- UI for sync progress (MCP tool only)

## Tasks

1. **Expand full sync state enum and schema** — Add `paused` and `waiting-for-ingestion` to the `inboxSyncState` enum. Add new columns (`full_sync_batch_index`, `full_sync_expected_total`, `full_sync_skipped`, `full_sync_scheduled_for_ingestion`, `full_sync_failed_to_upload_for_ingestion`). Create drizzle migration.

2. **Create `full-sync.command.ts`** — Main entry point replacing `StartFullSyncCommand` + `ExecuteFullSyncCommand`. Acquires lock, checks state and conditions (version mismatch, scope stats <20 in-progress, 5-minute cooldown, pause), decides next action, delegates to batch service. Handles all state transitions. Calls `$count` API on first run.

3. **Create `full-sync-batch.service.ts`** — Batch processing logic. Fetches Graph API page, iterates from saved batch index, calls ingestion API directly with 3 retries + exponential backoff. Saves batch index and updates counters after each message. Updates heartbeat. Returns control after 100 uploads or page exhaustion.

4. **Create `full-sync-reset.service.ts`** — Restart from scratch logic. Generates new version, resets nextLink/index/counters, sets state to `ready`.

5. **Create `FullSyncRecoveryService` cron** — Simple trigger that publishes retrigger events to a queue for all syncs not in `ready` or `paused` state. No condition checking in the cron itself.

6. **Extract `LiveCatchupRecoveryService`** — Move live catchup recovery logic out of `StuckSyncRecoveryService` into its own cron service. Remove old combined service.

7. **Add pause/resume/restart MCP tools** — Pause: flip state to `paused`. Resume: retrigger sync loop (enters decision logic for next state). Restart: call `full-sync-reset.service.ts`.

8. **Update `SyncProgressTool`** — Include `expectedTotal`, `skippedMessages`, `scheduledForIngestion`, `failedToUploadForIngestion` counters alongside existing date window and ingestion stats.

9. **Remove full sync from ingestion queue** — Remove priority config from queue. Remove `IngestFullSyncMessageCommand` handler from `IngestionListener`. Clean up full sync event types and publishing code. Remove old `StartFullSyncCommand` and `ExecuteFullSyncCommand`.

10. **Tests** — State transition unit tests, batch processing with resume-from-index, retry + cleanup logic, cron retrigger conditions, pause/resume/restart tools.
