# Design: Per-Tenant Structured Logging via Pino Child Loggers

**Ticket:** UN-17171 (multi-tenancy foundation)

## Problem

The current logging implementation has two separate loggers per tenant:

- `tenant.logger` = `new Logger('Tenant:acme')` — carries tenant name but loses service name
- `this.logger` = `new Logger(TenantSyncScheduler.name)` — carries service name but loses tenant name

A log entry is either `{"context":"Tenant:acme", "msg":"Starting sync"}` or `{"context":"TenantSyncScheduler", "msg":"..."}` — never both. In Grafana you cannot filter by tenant AND service simultaneously without regex hacks.

The agreed requirement (Decision #8 from the review with Michal) is that every log line inside a tenant sync must include both `tenantName` and `service` as **structured JSON fields**:

```json
{"tenantName": "acme", "service": "TenantSyncScheduler", "msg": "Starting sync"}
```

## Solution

### Overview

Use pino's native `.child()` API to create loggers with structured bindings. The app already uses `nestjs-pino` which wraps pino — we access the root pino instance via `PinoLogger.root` and create child loggers with `{ tenantName, service }` as bound fields.

A standalone helper function `getTenantLogger(ServiceClass)` reads the tenant name from `AsyncLocalStorage` and combines it with the passed service class name. This follows the pattern discussed in the design review meeting:

- **Tenant context** is carried by `AsyncLocalStorage` — set once by the scheduler at the start of `syncTenant()`, automatically available downstream
- **Service context** is passed explicitly by the caller — each service passes its own class (e.g., `getTenantLogger(TenantSyncScheduler)`)

### `getTenantLogger` Helper

```typescript
import type pino from 'pino';
import { PinoLogger } from 'nestjs-pino';
import { getCurrentTenant } from './tenant-context.storage';

type ServiceClass = { readonly name: string };

export function getTenantLogger(service: ServiceClass): pino.Logger {
  const tenant = getCurrentTenant();
  return PinoLogger.root.child({ tenantName: tenant.name, service: service.name });
}
```

### Usage in Services

```typescript
class TenantSyncScheduler {
  private async syncTenant(tenant: TenantContext): Promise<void> {
    await tenantStorage.run(tenant, async () => {
      const logger = getTenantLogger(TenantSyncScheduler);
      logger.info('Starting sync');
      // → {"tenantName":"acme", "service":"TenantSyncScheduler", "msg":"Starting sync"}

      const token = await tenant.auth.getAccessToken();
      logger.info({ token: smear(token) }, 'Token acquired');
    });
  }
}
```

### Constraint: Not Available in Constructors

Services are NestJS singletons — they are constructed once during module initialization, before any tenant sync runs. `AsyncLocalStorage` only has a value inside `tenantStorage.run()` callbacks. Therefore `getTenantLogger()` **cannot** be called in constructors. It must be called inside methods that execute within a sync context.

This was explicitly discussed and accepted in the design review: "slightly cumbersome but not terribly cumbersome — this is an option you can start with and we can then improve it."

### Changes to TenantContext

The `logger` property on `TenantContext` becomes a **pino child logger** (with `tenantName` bound) instead of a NestJS `Logger`. This base logger is still useful for places that need tenant-scoped logging but don't have a service class context (e.g., inside `TenantRegistry` during registration).

```typescript
// Before
import type { Logger } from '@nestjs/common';
export interface TenantContext {
  readonly logger: Logger;
  // ...
}

// After
import type { Logger } from 'pino';
export interface TenantContext {
  readonly logger: Logger;
  // ...
}
```

In `TenantRegistry.onModuleInit`, the logger creation changes from:

```typescript
const tenantLogger = new Logger(`Tenant:${name}`);
```

to:

```typescript
const tenantLogger = PinoLogger.root.child({ tenantName: name });
```

### Impact on `TenantSyncScheduler`

- Remove `private readonly logger = new Logger(TenantSyncScheduler.name)` (the service-scoped NestJS logger)
- Inside `syncTenant`, use `getTenantLogger(TenantSyncScheduler)` instead of `tenant.logger`
- For scheduler-level logs **outside** a tenant context (e.g., `onModuleInit` "No tenants registered"), keep a plain NestJS `Logger` or use `PinoLogger.root` directly since there's no tenant to scope to

### Log Output

Inside a tenant sync context:
```json
{"level": 30, "tenantName": "acme", "service": "TenantSyncScheduler", "msg": "Starting sync"}
{"level": 30, "tenantName": "acme", "service": "TenantSyncScheduler", "token": "eyJ...***", "msg": "Token acquired"}
```

Scheduler-level logs (no tenant context):
```json
{"level": 40, "msg": "No tenants registered — no sync jobs will be scheduled"}
```

### Error Handling

- `getTenantLogger()` calls `getCurrentTenant()` which throws if called outside of `tenantStorage.run()` — this is a programming error and should fail loudly
- If `PinoLogger.root` is accessed before `LoggerModule` initialization (shouldn't happen with correct module ordering), pino falls back to its default logger

### Testing Strategy

- **Unit test `getTenantLogger`:** Mock `PinoLogger.root` and `getCurrentTenant`, verify `.child()` is called with correct bindings
- **Update `TenantSyncScheduler` tests:** Verify that `getTenantLogger` is used instead of `tenant.logger` for sync logs
- **Update `TenantRegistry` tests:** Verify the pino child logger is created with `{ tenantName }` binding

## Out of Scope

- **Caching child loggers** — pino `.child()` is lightweight (creates a new object with merged bindings, no deep copy). Can be added later if profiling shows it matters.
- **Metrics with tenant label** — deferred per Decision #10
- **NestJS Logger wrapper** — the raw pino API (`.info()`, `.warn()`, `.error()`) is used directly. No wrapper to maintain NestJS `.log()` API compatibility, as pino's API is the industry standard for structured logging.

## Tasks

1. **Add `getTenantLogger` helper** — Create the function in `tenant-context.storage.ts` (or a new `tenant-logger.ts`), export from barrel. Add unit tests.

2. **Change `TenantContext.logger` to pino `Logger`** — Update the interface, update `TenantRegistry` to use `PinoLogger.root.child({ tenantName })`, update related tests.

3. **Refactor `TenantSyncScheduler` to use `getTenantLogger`** — Replace `tenant.logger` calls inside `syncTenant` with `getTenantLogger(TenantSyncScheduler)`. Keep a plain logger for scheduler-level (non-tenant) logs. Update tests.
