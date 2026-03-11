# PR Proposal

## Ticket
UN-17623

## Title
feat(outlook-semantic-mcp): full sync state versioning and stuck sync recovery

## Description
- Rename `syncState`/`syncStartedAt` to `fullSyncState`/`lastFullSyncStartedAt` and add granular intermediate states (`fetching-emails`, `performing-file-diff`, `processing-file-diff-changes`, `full-sync-finished`)
- Introduce `fullSyncVersion` UUID generated on each sync start; all DB updates and AMQP event handlers use it as a version guard to prevent stale writes from previous runs
- Add `StuckSyncRecoveryService` cron (every minute) that detects syncs stuck for >15 minutes via `GREATEST(last_full_sync_started_at, updated_at)` and publishes a recovery AMQP event
- Add `FullSyncRecoveryListener` that resets stuck sync state and re-triggers the full sync
