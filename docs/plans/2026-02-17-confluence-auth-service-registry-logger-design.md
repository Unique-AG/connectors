# Design: confluence auth service-registry logger ownership

**Ticket:** UN-17171

## Problem
Confluence authentication currently creates class-local loggers in the auth factory and strategy layer. This breaks consistency with tenant-aware structured logging and makes observability context depend on local class behavior instead of tenant wiring. The desired behavior is that Confluence auth logs always include structured tenant and service identity fields (`tenantName`, `service`) and that auth classes do not create their own logger instances.

The current helper-based approach (`getTenantLogger`) proves the context pattern works, but logger ownership is not centralized with the service wiring mechanism. For this refactor, logger ownership should align with service lifecycle ownership so the same registry-driven flow that provides tenant-scoped services also provides tenant-scoped service loggers.

## Solution

### Overview
Move tenant-aware logger ownership into `ServiceRegistry` and inject Confluence auth loggers through the same composition path used for tenant services. `TenantRegistry` remains the bootstrap point, but instead of Confluence auth classes creating local loggers, tenant wiring acquires a service logger from `ServiceRegistry` and passes it into the Confluence auth factory and strategies.

This keeps the scope intentionally narrow: Confluence auth only. The pattern is intentionally reusable so later work can apply it to other services without redesigning the approach.

### Architecture
- Extend `ServiceRegistry` to own tenant logger storage and service logger derivation.
- Preserve `ConfluenceAuthAbstract` as the runtime key for service registration and lookup.
- Update tenant bootstrap (`TenantRegistry`) to register tenant base logger and derive Confluence auth logger from `ServiceRegistry`.
- Update `ConfluenceAuthFactory.createAuthStrategy(...)` to accept an injected logger and propagate it to strategy constructors.
- Update Confluence strategies (notably `OAuth2LoAuthStrategy`) to log exclusively with injected logger and remove local `new Logger(...)` fields.
- Keep structured keys unchanged: `tenantName` and `service`.

### Error Handling
No auth behavior changes are intended:
- Preserve OAuth2LO network error handling.
- Preserve non-2xx token response handling.
- Preserve malformed response validation and thrown errors.
- Preserve PAT behavior as static token pass-through.

Logger ownership failures should surface at composition time (tenant registration / service wiring), not during token acquisition hot path.

### Testing Strategy
Focus on behavioral and wiring-level tests:
1. `ServiceRegistry` tests: logger registration/retrieval, tenant isolation, and error paths.
2. `ConfluenceAuthFactory` tests: mode selection still correct, logger dependency is propagated.
3. `OAuth2LoAuthStrategy` tests: logs through injected logger while preserving token and error behavior.
4. Integration-touch checks: tenant scheduler/service-resolution flow remains compatible with `ConfluenceAuthAbstract`.

Use existing test setup and avoid adding broad new integration suites unless a concrete gap appears.

## Out of Scope
- Refactoring Unique auth logging in this change.
- Platform-wide logging policy redesign.
- Renaming structured log fields (`tenantName`, `service` stay as-is).
- Altering Confluence auth public runtime contract (`ConfluenceAuthAbstract`).
- Changing token lifecycle semantics beyond logger ownership.

## Tasks
1. **Add logger ownership to `ServiceRegistry`** - Introduce per-tenant logger storage and service logger derivation with consistent structured context.
2. **Update tenant wiring to register/use registry logger** - Register tenant base logger and request Confluence auth service logger through registry APIs.
3. **Refactor `ConfluenceAuthFactory` signatures** - Accept injected logger and pass it to strategy constructors.
4. **Refactor Confluence strategies to injected logger** - Remove local logger construction and route logs through injected logger only.
5. **Update tests for registry + auth wiring** - Extend `ServiceRegistry` tests and adjust factory/strategy tests for the new logger dependency flow.
6. **Prepare follow-up generalization** - Track a separate future effort to apply the same pattern to other tenant-scoped services.
