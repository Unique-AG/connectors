# Design: Confluence Synchronization Service

## Problem

The confluence-connector has a `TenantSyncScheduler` that handles both scheduling concerns (cron jobs, lifecycle) and business logic (token acquisition, scanning guard). The scheduler currently hits a `// TODO: Full sync pipeline` dead end. We need a proper synchronization service that:

1. Owns the sync pipeline business logic (separated from scheduling concerns)
2. Uses tenant-scoped pino loggers to validate the tenant logger functionality
3. Follows the patterns established by the sharepoint-connector's `SharepointSynchronizationService`

## Solution

### Overview

Create a `ConfluenceSynchronizationService` as a per-tenant service registered in the `ServiceRegistry`. The scheduler becomes a thin orchestrator that delegates to this service. For now, the sync service acquires a Confluence token and logs lifecycle messages, proving the tenant logger pipeline works end-to-end.

### Architecture

**Service Registration:**
- `ConfluenceSynchronizationService` is a concrete class (no abstract token needed — no multiple strategies)
- Created per-tenant in `TenantRegistry.onModuleInit()` and registered in `ServiceRegistry`
- The service receives `ServiceRegistry` in its constructor to access the tenant logger and other per-tenant services (like `ConfluenceAuth`)

**Responsibility Split:**
- `TenantSyncScheduler` — thin: cron management, shutdown guard, delegates to sync service
- `ConfluenceSynchronizationService.synchronize()` — owns: `isScanning` guard, token acquisition, sync pipeline, error handling

**Data Flow:**
```
Cron tick / onModuleInit
  → TenantSyncScheduler.syncTenant(tenant)
    → tenantRegistry.run(tenant, ...)
      → serviceRegistry.getService(ConfluenceSynchronizationService).synchronize()
        → logger.info('Starting sync')
        → ConfluenceAuth.acquireToken()
        → logger.info({ token: smear(token) }, 'Token acquired')
        → logger.info('Sync completed')
```

**File Structure:**
```
src/synchronization/
  confluence-synchronization.service.ts    # The sync service
  confluence-synchronization.service.spec.ts  # Unit tests
```

**Modified Files:**
- `src/tenant/tenant-registry.ts` — register `ConfluenceSynchronizationService` per tenant
- `src/scheduler/tenant-sync.scheduler.ts` — simplify `syncTenant()` to delegate to sync service
- `src/scheduler/tenant-sync.scheduler.spec.ts` — update tests for simplified scheduler

### Error Handling

- `isScanning` guard on `TenantContext` prevents concurrent syncs per tenant (already exists)
- `try/catch/finally` around the sync pipeline; `isScanning = false` in `finally`
- Token acquisition errors caught and logged with `sanitizeError()`
- All logs go through tenant-scoped pino logger (automatic `tenantName` + `service` fields)

### Testing Strategy

- Unit test `synchronize()` directly — the service is created manually, not via NestJS DI
- Mock `ServiceRegistry.getServiceLogger()` for a mock pino logger
- Mock `ConfluenceAuth.acquireToken()` for token scenarios
- Test cases:
  - Happy path: logs start, acquires token, logs token, logs completed
  - `isScanning` guard: skips when already scanning
  - Token failure: catches error, logs it, resets `isScanning`
- Update `TenantSyncScheduler` tests to verify delegation to sync service

## Out of Scope

- Actual Confluence API calls (spaces, pages, content fetching)
- Content sync, permissions sync pipelines
- Metrics/OpenTelemetry instrumentation
- Sync result types (success/failure/skipped discriminated unions)
- Module definition (service is per-tenant via ServiceRegistry, not via NestJS module)

## Tasks

1. **Create `ConfluenceSynchronizationService`** — New file in `src/synchronization/`. Concrete class with `synchronize()` method that acquires a token and logs lifecycle messages using the tenant logger. Constructor takes `ServiceRegistry`.

2. **Register service per tenant in `TenantRegistry`** — In `onModuleInit()`, after creating auth services, instantiate and register `ConfluenceSynchronizationService` for each tenant.

3. **Simplify `TenantSyncScheduler.syncTenant()`** — Remove token acquisition and `isScanning` guard logic. Replace with a call to `serviceRegistry.getService(ConfluenceSynchronizationService).synchronize()`.

4. **Write unit tests for the sync service** — Test happy path, concurrent scan guard, and token failure scenarios.

5. **Update scheduler tests** — Adjust existing `TenantSyncScheduler` spec to reflect the simplified delegation pattern.
