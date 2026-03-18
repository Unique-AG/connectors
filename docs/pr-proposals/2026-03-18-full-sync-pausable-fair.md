# PR Proposal

## Title
feat(outlook-semantic-mcp): pausable fair full sync with direct ingestion

## Description
- Decouple full sync from RabbitMQ ingestion queue — call ingestion API directly with retries, preventing full sync from blocking live catchup for other users
- Implement self-throttling sync loop: upload 100 messages per burst, park in `waiting-for-ingestion`, cron resumes when pipeline drains below 20 in-progress
- Add `paused` and `waiting-for-ingestion` states with pause/resume/restart MCP tools and granular progress counters (expectedTotal, skipped, scheduled, failedToUpload)
- Split `StuckSyncRecoveryService` into separate `FullSyncRecoveryService` and `LiveCatchupRecoveryService` cron jobs
- Add per-message resumability via batch index tracking within Graph API pages
