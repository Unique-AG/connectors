# PR Proposal

## Title
feat(confluence-connector): add synchronization service with tenant-scoped logging

## Description
- Create `ConfluenceSynchronizationService` as a per-tenant service that owns the sync pipeline lifecycle (scanning guard, token acquisition, logging)
- Simplify `TenantSyncScheduler` to a thin cron orchestrator that delegates to the sync service
- Validate tenant logger functionality end-to-end: sync logs include `tenantName` and `service` fields automatically
- Add unit tests for the sync service and update scheduler tests
