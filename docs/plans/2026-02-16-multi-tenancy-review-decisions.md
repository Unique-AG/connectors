# Multi-Tenancy Design Review — Decision Summary

**Date:** 2026-02-16
**Participants:** Lorand Sandor, Michal Simka (Ostrzy)
**Sources:** [PR #281 review](https://github.com/Unique-AG/connectors/pull/281), follow-up meeting
**Ticket:** UN-17171

---

## Decisions

### 1. Use AsyncLocalStorage for tenant context propagation

**Status:** Agreed — promoted from "future consideration" to core design.

**Context:** Michal raised that passing the whole `TenantContext` object through every function call (prop-drilling) is cumbersome in JS/TS. He proposed using `AsyncLocalStorage` to set the tenant context once at the start of `syncTenant()` so downstream code can retrieve per-tenant services (logger, API clients, etc.) without explicit passing.

**Decision:** Implement `AsyncLocalStorage`-based context from the start. The scheduler sets the tenant context once per sync invocation. Downstream services retrieve what they need via a helper (e.g., `this.tenantContext.get(Logger)`). This is similar to NestJS `ClsModule` / request-scoped context in HTTP servers.

**Rationale:** The tenant context will grow to include Confluence API client, Unique API client, rate limiters, etc. Starting with AsyncLocalStorage avoids a large refactor later. The pattern is well-suited because we set context once and only read it downstream — no mutation concerns.

---

### 2. Tenant lifecycle status: `active` | `inactive` | `deleted` (following SPC pattern)

**Status:** Agreed — already updated in a previous commit, confirmed in meeting.

**Context:** Michal asked whether the tenant `enabled: boolean` flag should follow the SPC (SharePoint Connector) site status pattern with three states: `active`, `inactive`, `deleted`.

**Decision:** Use `status` field with three values:
- `active` (default) — tenant is registered, auth initialized, cron scheduled
- `inactive` — config is validated but tenant is not registered (temporary pause)
- `deleted` — config is NOT validated, tenant not registered; when the sync pipeline is implemented, triggers cleanup of previously ingested data

**Rationale:** Consistent with SPC. The `deleted` status enables a future data cleanup workflow — marking a tenant as deleted signals the system to remove ingested data, not just stop syncing.

---

### 3. Per-tenant cron jobs (not a single global cron)

**Status:** Agreed — confirmed in meeting.

**Context:** Michal pointed out the wording in the design was misleading (sounded like a single cron iterating tenants). He asked whether per-tenant or global cron makes more sense.

**Decision:** Each tenant gets its own `CronJob` registered dynamically via NestJS `SchedulerRegistry`. This allows different tenants to have different `scanIntervalCron` expressions (e.g., high-priority tenant syncs every 30 min, low-priority once a day).

**Rationale:** Follows the SPC pattern. Per-tenant crons are straightforward with `SchedulerRegistry` and allow per-tenant scheduling flexibility. No strong reason to use a single global cron.

---

### 4. `isScanning` flag lives on `TenantContext`

**Status:** Agreed.

**Context:** Michal noted `isScanning` shouldn't live in a separate `Set<string>` on the scheduler.

**Decision:** `isScanning` is a mutable boolean on `TenantContext`. The scheduler checks and sets it directly on the tenant object.

---

### 5. TenantRegistry must not become a god class — use factories

**Status:** Agreed — already in design, reinforced in meeting.

**Context:** Michal emphasized splitting per-tenant resource construction into dedicated factory classes. The registry should be a thin orchestrator that delegates to factories.

**Decision:** Each category of per-tenant resource gets its own factory (e.g., `TenantAuthFactory`, `ConfluenceClientFactory`, `UniqueClientFactory`). The registry injects all factories and orchestrates assembly. Clients/services are created once at startup and cached in the `TenantContext` — not recreated per sync.

---

### 6. Env var resolver: let the schema decide if missing value is an error

**Status:** Agreed.

**Context:** Michal questioned why the `envResolvableStringSchema` Zod transform validates that the env var is set. If the field is required, Zod's schema layer already handles that.

**Decision:** The env resolver (`os.environ/` transform) simply resolves the reference — it returns the value or `undefined` if not set. The Zod schema (required vs optional) decides whether a missing value is an error. This avoids duplicating validation logic.

---

### 7. `os.environ/` resolution defaults to `Redacted` wrapping

**Status:** Agreed — keep two schemas with Redacted as default.

**Context:** Michal initially suggested making env-loaded values Redacted by default with an explicit opt-out for non-secrets. He then reconsidered, noting that since you explicitly choose to use the env resolver in the schema, it's always for secrets — so always Redacted.

**Decision:** Keep two Zod utility schemas:
- `envResolvableRedactedStringSchema` (default for secrets) — resolves `os.environ/` and wraps in `Redacted`
- `envResolvablePlainStringSchema` (explicit opt-out) — resolves `os.environ/` without `Redacted` wrapping, for the rare non-secret env reference

In practice, the Redacted variant is the one used in schema definitions. The plain variant exists as an explicit escape hatch.

---

### 8. Logger: per-service AND per-tenant, investigate pino child loggers

**Status:** Agreed in principle — implementation approach to be refined.

**Context:** Michal noted that `new Logger('Tenant:acme')` loses the service name context. He wants logs to have both the service name (e.g., `TenantSyncScheduler`) and the tenant name (e.g., `acme`) as filterable properties. He asked whether `new Logger(SchedulerService.name)` is already filterable in Grafana — it is, but only as the NestJS context string, not a separate structured field.

**Decision:** Logs should include both service context and tenant context. Two options discussed:
1. Use pino child loggers with `tenantName` as a structured field, retrieved from `AsyncLocalStorage`
2. Use a helper that enriches a service-scoped logger with tenant context from `AsyncLocalStorage`

Start with a simple approach (can be NestJS Logger with combined context string like `Tenant:acme:TenantSyncScheduler`), then improve to structured fields once the foundation is working. Don't over-engineer the logging on this ticket.

---

### 9. Tenant name validation: simple regex, uniqueness check

**Status:** Agreed.

**Context:** Michal suggested basic sanity checking on extracted tenant names — fail-fast on invalid characters. Lorand proposed also checking uniqueness.

**Decision:** Validate tenant names with a simple regex (lowercase alphanumeric + dashes: `^[a-z0-9]+(-[a-z0-9]+)*$`). Fail-fast at startup if:
- A tenant name contains invalid characters (treated as misconfiguration)
- Two tenant config files resolve to the same name (duplicate)

---

### 10. Metrics: scoped per-tenant, but deferred

**Status:** Agreed to defer — not in scope for this ticket.

**Context:** Michal mentioned metrics should carry a `tenant` label. He suggested partial application or currying for metric helpers. But agreed this adds complexity and should wait.

**Decision:** Metrics with tenant labels are out of scope for this ticket. The design acknowledges it as a future addition. When implemented, metrics will leverage `AsyncLocalStorage` to automatically include the tenant label.

---

### 11. Rate limiting: Confluence per-tenant, Unique shared — deferred

**Status:** Agreed to defer.

**Context:** Lorand noted Confluence rate limiting should be per-instance/per-tenant while Unique rate limiting should be global/shared. Michal agreed but said this is a detail for later — for starters, divide rate limits by number of tenants if needed.

**Decision:** Rate limiting architecture noted for future implementation:
- Confluence API rate limiter: per-tenant (each tenant may hit a different Confluence instance)
- Unique API rate limiter: global shared (all tenants share the same Unique platform instance)
- Potential optimization: detect tenants sharing the same Confluence instance and merge their rate limiters

---

### 12. OpenTelemetry / `@Span` decorators: deferred

**Status:** Agreed to defer.

**Context:** Lorand mentioned Niku's `@Span` decorators from the SPC. Michal said it's good practice but not a priority — neither has much experience with it yet.

**Decision:** Skip OpenTelemetry spans for this ticket. Add telemetry after the multi-tenancy foundation is running. Focus on getting the core architecture right first.

---

## Summary of Design Changes

| Area | Before Review | After Review |
| --- | --- | --- |
| AsyncLocalStorage | Future consideration | Core part of design |
| Tenant status | `enabled: boolean` | `status: active \| inactive \| deleted` |
| Cron scheduling | Ambiguous wording | Explicitly per-tenant CronJobs |
| `isScanning` location | Scheduler's `Set<string>` | `TenantContext.isScanning` boolean |
| Env var resolver | Validates missing vars | Defers to Zod schema (required/optional) |
| `os.environ/` default | Redacted by default | Confirmed: Redacted by default, plain as opt-out |
| Logger | Single `Tenant:name` context | Per-service + per-tenant; investigate pino child loggers |
| Tenant name validation | None | Regex + uniqueness check |
| Metrics | Mentioned | Explicitly deferred |
| Rate limiting | In "Out of Scope" | Noted architecture (per-tenant vs shared) |
| OpenTelemetry | Not mentioned | Explicitly deferred |
