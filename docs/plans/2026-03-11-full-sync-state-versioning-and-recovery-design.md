# Design: Full Sync State Versioning and Recovery

**Ticket:** UN-17623

## Problem

The current full-sync system has three issues:

1. **Coarse state visibility** — `syncState` only distinguishes `idle/running/failed`, giving no insight into which phase the sync is in (fetching, diffing, processing).
2. **Stale counter updates** — When `messagesProcessed` is incremented via AMQP events, there is no guard against events from a previous sync run incrementing the counter of the current run.
3. **No recovery from stuck syncs** — If a sync crashes mid-way (e.g. OOM, pod restart), it stays in a non-`idle` state forever and the 5-minute rerun guard never clears, blocking future syncs permanently.

## Solution

### Overview

Rename the existing sync columns to be more explicit (`fullSyncState`, `lastFullSyncStartedAt`), introduce granular intermediate states, add a `fullSyncVersion` UUID that acts as a distributed optimistic lock across all sync-related DB updates and AMQP events, and add a cron-based recovery service that detects and unsticks stuck syncs.

### Architecture

#### Schema Changes

Column renames:
- `sync_state` → `full_sync_state`
- `sync_started_at` → `last_full_sync_started_at`

Enum `inbox_sync_state` updated:
- Rename `idle` → `full-sync-finished`
- Add: `fetching-emails`, `performing-file-diff`, `processing-file-diff-changes`
- Keep: `running` (used as a transitional guard in `acquireSyncLock`), `failed`

New column: `full_sync_version` (UUID, nullable)

#### State Machine

```
full-sync-finished ──► fetching-emails ──► performing-file-diff
                                                    │
                                    processing-file-diff-changes
                                                    │
                                          full-sync-finished
                          (any throw at any point) ──► failed
```

#### Version-Based Optimistic Lock

`acquireSyncLock()` generates a fresh `crypto.randomUUID()` as `fullSyncVersion` and writes it to the DB alongside `fullSyncState: 'fetching-emails'`. Every subsequent `UPDATE inbox_configuration` in `runSync()` includes `WHERE full_sync_version = $version`. This ensures that if a recovery cron resets the state and starts a new sync with a new version, any in-flight DB writes from the old run silently no-op.

#### AMQP Event Versioning

All AMQP events published during full sync carry `fullSyncVersion` in their payload. Every AMQP handler that writes back to `inbox_configuration` (currently `IngestEmailFromFullSyncCommand`) uses that version in a `WHERE full_sync_version = $version` guard on the update.

#### Stuck Sync Recovery

`StuckSyncRecoveryService` runs as a NestJS cron every minute. It queries:

```sql
SELECT * FROM inbox_configuration
WHERE full_sync_state NOT IN ('full-sync-finished', 'failed')
AND GREATEST(last_full_sync_started_at, updated_at) < NOW() - INTERVAL '15 minutes'
```

For each stuck config it publishes a `unique.outlook-semantic-mcp.full-sync.recovery-requested` AMQP event with `{ userProfileId }`.

`FullSyncRecoveryListener` consumes this event, resets `fullSyncState = 'full-sync-finished'` (so `acquireSyncLock` no longer sees a running sync), then calls `FullSyncCommand.run(subscriptionId)`.

### Error Handling

- Any unhandled error in `runSync()` issues a version-guarded update to `fullSyncState: 'failed'`. If the version no longer matches (recovery already reset it), the failed write is ignored.
- Counter increments from stale AMQP events silently no-op via version mismatch — no error is thrown.
- If the recovery cron itself fails to publish, the stuck config will be retried on the next cron tick.

### Testing Strategy

Use the existing integration test setup. Focus on behavioral tests for:
- `acquireSyncLock` generating a new version and rejecting concurrent runs
- Version-guarded counter increment ignoring stale versions
- `StuckSyncRecoveryService` selecting only configs past the 15-minute threshold using `GREATEST(last_full_sync_started_at, updated_at)`

## Out of Scope

- Persisting granular per-phase timing/metrics
- Surfacing the new intermediate states differently in the MCP `sync_progress` tool output (states are passed through as-is)
- Configurable stuck-sync timeout (hardcoded 15 minutes)

## Tasks

1. **Write the Drizzle migration** — Rename `sync_state` → `full_sync_state`, `sync_started_at` → `last_full_sync_started_at`, rename enum value `idle` → `full-sync-finished`, add enum values `fetching-emails`, `performing-file-diff`, `processing-file-diff-changes`, add `full_sync_version` UUID nullable column.

2. **Update schema and all TypeScript references** — Update `inbox-configuration.table.ts` with new column names, new enum, and `fullSyncVersion`. Update every file that reads or writes `syncState`, `syncStartedAt`.

3. **Thread version through FullSyncCommand** — `acquireSyncLock()` generates and stores `fullSyncVersion`. `runSync()` transitions through granular states using version-guarded updates. On error, version-guarded `failed` update.

4. **Add version to AMQP event payload and guard counter updates** — Add `fullSyncVersion` to `MessageEventDto` full-sync payload. Update `IngestEmailFromFullSyncCommand` to use version-guarded `WHERE` on the `messagesProcessed` increment.

5. **Implement StuckSyncRecoveryService** — NestJS cron (every minute) querying stuck configs using `GREATEST(last_full_sync_started_at, updated_at) < NOW() - 15 minutes`, publishing `full-sync.recovery-requested` AMQP events.

6. **Implement FullSyncRecoveryListener** — Consumes `full-sync.recovery-requested`, resets `fullSyncState = 'full-sync-finished'`, then calls `FullSyncCommand.run(subscriptionId)`.

7. **Update GetFullSyncStatsQuery and search tool** — Map new granular states to the stats/progress output and the search warning logic.
