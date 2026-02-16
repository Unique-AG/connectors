# Design: Multi-Tenancy Foundation

**Ticket:** UN-17171 | **ADR:** [Confluence Connector Multi-Tenancy Architecture](https://unique-ch.atlassian.net/wiki/spaces/ptf/pages/1906737185)

## Problem

The confluence-connector operates in single-tenant mode: it reads the first tenant config file, registers it globally via NestJS `ConfigModule`, and creates a single auth strategy. All env var secrets (`CONFLUENCE_CLIENT_SECRET`, `CONFLUENCE_PAT`, `ZITADEL_CLIENT_SECRET`) are global — different credentials per tenant are not supported.

## Solution

### Overview

Transform the connector to support multiple Confluence tenants from a single deployment across five layers:

1. **Config & Secrets (Layer 1):** Replace the implicit secret injection (`injectSecretsFromEnvironment`) with LiteLLM-style `os.environ/VAR_NAME` references in tenant YAML. Secrets are resolved inside Zod transforms during validation. Tenant name is derived from the filename and validated (lowercase alphanumeric + dashes, unique across files). A top-level `status` field (`active` | `inactive` | `deleted`) controls tenant lifecycle — only `active` tenants are registered and scheduled.

2. **TenantRegistry (Layer 2):** A global `TenantRegistry` service holds a `Map<string, TenantContext>`. Each `TenantContext` bundles the tenant's config, a pre-configured auth strategy with its own `TokenCache`, and a scoped logger. The registry is a **thin orchestrator** delegating construction to dedicated factories — it must not become a god class. This replaces the current `ConfigModule.forRoot` registration of tenant-scoped config.

3. **Scheduler (Layer 3):** Each tenant gets its own `CronJob` registered dynamically at startup via NestJS `SchedulerRegistry`, using the tenant's `scanIntervalCron` expression. Each `TenantContext` carries an `isScanning` flag so overlapping cron ticks for the same tenant are skipped. For this ticket, the sync action acquires an auth token per tenant (proving per-tenant auth works end-to-end).

4. **Tenant Context Propagation (Layer 4):** `AsyncLocalStorage` provides implicit access to the current `TenantContext` during a sync execution. The scheduler sets the context once at the start of `syncTenant()`, and downstream services retrieve per-tenant resources (logger, API clients, config) via a helper — no prop-drilling required.

5. **Observability (Layer 5):** Logs include both service context and tenant context as structured fields. Start with a simple approach (combined NestJS Logger context string), with room to evolve to pino child loggers for dedicated `tenantName` JSON fields. Metrics with tenant labels are deferred to a later ticket.

### Key Decisions

#### Decision 1: Auth wiring — combined TenantContext vs separate ConfluenceAuthModule

**Option A (chosen): Combined TenantContext with `auth: TenantAuth` baked in.**
`TenantAuthFactory` creates per-tenant `TenantAuth` instances (auth strategy + token cache) at startup. `TenantRegistry` injects the factory and wires the result into `TenantContext.auth`. `ConfluenceAuthModule` and `ConfluenceAuthenticationService` are removed. Consumers call `tenant.auth.getAccessToken()` directly.

**Option B (rejected): Keep ConfluenceAuthModule, make it tenant-aware.**
`ConfluenceAuthenticationService` would hold a `Map<string, { strategy, cache }>` internally, and its signature would change from `getAccessToken()` to `getAccessToken(tenantName: string)`. `TenantContext` would NOT include auth — consumers would need to inject both `TenantRegistry` and `ConfluenceAuthenticationService`, passing `tenantName` strings to look things up in two places.

**Why Option A:** In practice, auth is never used without tenant config. The combined approach means one object, one injection, no string-based lookups. When future layers are added (API clients, rate limiters), they'll also live on `TenantContext` — it's the single "handle" for everything tenant-scoped. The auth strategy classes (`OAuth2LoAuthStrategy`, `PatAuthStrategy`) and `TokenCache` remain unchanged — only the NestJS wiring layer (`ConfluenceAuthModule`, `ConfluenceAuthenticationService`, `CONFLUENCE_AUTH_STRATEGY` symbol) is removed.

#### Decision 2: Cron scheduling — one global job vs per-tenant jobs

**Option A: Single global cron tick.** One cron job fires at a fixed interval (e.g., every minute). On each tick, the scheduler checks each tenant's `scanIntervalCron` to decide whether that tenant should run this cycle. Simpler to manage, but requires the scheduler to track "last run" timestamps per tenant and compare against cron expressions.

**Option B (chosen): One CronJob per tenant, registered dynamically.** Each tenant gets its own `CronJob` registered via NestJS `SchedulerRegistry` at startup, using that tenant's `scanIntervalCron` expression. This follows the same pattern as the SharePoint connector (which uses `SchedulerRegistry.addCronJob()` with `CronJob` from the `cron` package), extended from 1 job to N jobs.

**Why Option B:** Each tenant already defines its own `scanIntervalCron` in the processing config. Dynamic registration is the natural extension of the existing SPC pattern. It's simpler than tracking last-run timestamps, and NestJS `SchedulerRegistry` handles lifecycle (start/stop/cleanup) natively.

### Architecture

#### Component Layout

```
┌──────────────────────────────────────────────────────────┐
│ AppModule                                                │
│                                                          │
│  ConfigModule.forRoot (app-level config only)            │
│  TenantModule (global)                                   │
│    ├─ TenantRegistry                                     │
│    │    └─ Map<string, TenantContext>                     │
│    │         ├─ name, config, logger, isScanning          │
│    │         └─ auth: TenantAuth                          │
│    └─ AsyncLocalStorage<TenantContext> (tenant context)   │
│         └─ getCurrentTenant() helper                      │
│  SchedulerModule                                         │
│    └─ TenantSyncScheduler (sets AsyncLocalStorage per    │
│         sync, registers per-tenant CronJobs)              │
│  LoggerModule, ProbeModule, OpenTelemetryModule           │
└──────────────────────────────────────────────────────────┘
```

#### Layer 1: Config & Secret Resolution

**`os.environ/` pattern (LiteLLM-style):**

Tenant YAML files reference environment variables using the `os.environ/VAR_NAME` prefix:

```yaml
# acme-tenant-config.yaml
confluence:
  instanceType: data-center
  baseUrl: https://confluence.acme.com
  auth:
    mode: oauth_2lo
    clientId: my-app-id
    clientSecret: "os.environ/ACME_CONFLUENCE_CLIENT_SECRET"
  apiRateLimitPerMinute: 100
  ingestSingleLabel: ai-ingest
  ingestAllLabel: ai-ingest-all

unique:
  serviceAuthMode: external
  zitadelOauthTokenUrl: https://zitadel.acme.com/oauth/v2/token
  zitadelProjectId: "os.environ/ACME_ZITADEL_PROJECT_ID"
  zitadelClientId: my-client
  zitadelClientSecret: "os.environ/ACME_ZITADEL_CLIENT_SECRET"
  ingestionServiceBaseUrl: http://node-ingestion:8091
  scopeManagementServiceBaseUrl: http://node-scope-management:8094
  apiRateLimitPerMinute: 100

processing:
  scanIntervalCron: "0 */2 * * *"
  concurrency: 1
```

**Resolution happens inside Zod transforms**, not as a preprocessing step. New Zod utility schemas:

```typescript
const ENV_REF_PREFIX = 'os.environ/';

// Base: resolves os.environ/ references to actual env var values.
// Does NOT validate whether the env var is set — the Zod schema
// (required vs optional) decides whether a missing value is an error.
const envResolvableStringSchema = z.string().transform((val) => {
  if (!val.startsWith(ENV_REF_PREFIX)) return val;
  const varName = val.slice(ENV_REF_PREFIX.length);
  return process.env[varName] ?? '';
});

// Default for secret fields: resolve env ref, then wrap in Redacted.
// This is the schema used in most places — env-loaded values are
// assumed to be secrets unless explicitly opted out.
const envResolvableRedactedStringSchema = envResolvableStringSchema
  .pipe(z.string().min(1))
  .transform((val) => new Redacted(val));

// Explicit opt-out for non-secret env references (rare).
// Returns a plain string without Redacted wrapping.
const envResolvablePlainStringSchema = envResolvableStringSchema
  .pipe(z.string().min(1));
```

**The `injectSecretsFromEnvironment()` function is removed entirely.** The YAML is the single source of truth for which env var each field reads from.

**Tenant name extraction:**

| Filename | Tenant Name |
| --- | --- |
| `default-tenant-config.yaml` | `default` |
| `acme-tenant-config.yaml` | `acme` |
| `acme-corp-tenant-config.yaml` | `acme-corp` |

Rule: strip the `-tenant-config.yaml` suffix from the filename (without directory path).

**Tenant name validation:** Extracted names are validated with regex `^[a-z0-9]+(-[a-z0-9]+)*$` (lowercase alphanumeric + dashes). Fail-fast at startup if:
- A tenant name contains invalid characters (misconfiguration)
- Two tenant config files resolve to the same name (duplicate)

**Tenant lifecycle status:** A top-level `status` field controls tenant behavior (similar to SPC site statuses):

| Status | Behavior |
| --- | --- |
| `active` | Tenant is registered, auth is initialized, cron job is scheduled. Default if `status` is omitted. |
| `inactive` | Tenant is logged as skipped and not registered. Config is still validated. Use for temporarily pausing a tenant without losing its config. |
| `deleted` | Tenant is logged as skipped and not registered. Config is NOT validated (may contain errors). When the sync pipeline is implemented, this status will trigger cleanup of previously ingested data. |

```yaml
status: inactive  # This tenant is temporarily paused
confluence:
  # ... (config is validated but tenant is not registered)
```

```yaml
status: deleted  # This tenant's ingested data should be cleaned up
confluence:
  # ... (config is NOT validated, may contain errors)
```

**`getTenantConfigs()` return type changes:**

```typescript
interface NamedTenantConfig {
  name: string;
  config: TenantConfig;
}

function getTenantConfigs(): NamedTenantConfig[]
```

#### Layer 2: TenantRegistry

A global NestJS provider holding all tenant contexts. The registry is a **thin orchestrator** — it delegates construction of per-tenant services to dedicated classes/factories rather than building everything inline. This prevents the registry from becoming a god class as `TenantContext` grows.

**Factory pattern:** Each category of per-tenant resource gets its own factory. The registry injects factories and delegates construction to them, keeping its `onModuleInit` a simple assembly loop.

```typescript
interface TenantAuth {
  getAccessToken(): Promise<string>;
}

@Injectable()
export class TenantAuthFactory {
  create(confluenceConfig: ConfluenceConfig): TenantAuth {
    const strategy = createAuthStrategy(confluenceConfig);
    const tokenCache = new TokenCache();
    return {
      getAccessToken: () => tokenCache.getToken(() => strategy.acquireToken()),
    };
  }
}
```

```typescript
interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  readonly auth: TenantAuth;
  isScanning: boolean;
  // TODO: Add per-tenant Confluence API client (via ConfluenceClientFactory)
  // TODO: Add per-tenant Unique API client (via UniqueClientFactory)
  // TODO: Add per-tenant rate limiters (via RateLimiterFactory)
}

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly tenants = new Map<string, TenantContext>();

  constructor(private readonly authFactory: TenantAuthFactory) {}

  onModuleInit() {
    const configs = getTenantConfigs();
    for (const { name, config } of configs) {
      const logger = new Logger(`Tenant:${name}`);

      this.tenants.set(name, {
        name,
        config,
        logger,
        auth: this.authFactory.create(config.confluence),
        isScanning: false,
      });

      logger.log('Tenant registered');
    }
  }

  get(name: string): TenantContext { ... }
  getAll(): TenantContext[] { ... }
  get size(): number { ... }
}
```

**Design principle:** As more per-tenant resources are added, each gets its own factory (e.g., `ConfluenceClientFactory`, `UniqueClientFactory`, `RateLimiterFactory`). The registry injects all factories and orchestrates the assembly — but never owns the construction logic itself. Clients and services are created once at startup and cached in the `TenantContext` — not recreated per sync.

#### Layer 4: Tenant Context Propagation (AsyncLocalStorage)

`AsyncLocalStorage` provides implicit access to the current `TenantContext` during a sync execution, avoiding prop-drilling through every function call. This was agreed as a core part of the design (not deferred) because `TenantContext` will grow to include Confluence API client, Unique API client, rate limiters, etc. — passing it explicitly everywhere would quickly become cumbersome.

**How it works:**

```typescript
import { AsyncLocalStorage } from 'node:async_hooks';

const tenantStorage = new AsyncLocalStorage<TenantContext>();

// Scheduler sets context once per sync
async syncTenant(tenant: TenantContext) {
  await tenantStorage.run(tenant, async () => {
    // All downstream code can access tenant context implicitly
    await this.doSync();
  });
}

// Downstream helper — retrieves current tenant context
function getCurrentTenant(): TenantContext {
  const tenant = tenantStorage.getStore();
  if (!tenant) throw new Error('No tenant context — called outside of sync execution');
  return tenant;
}

// Usage in any downstream service
class SomeService {
  doWork() {
    const tenant = getCurrentTenant();
    const logger = tenant.logger;
    const config = tenant.config;
    // ...
  }
}
```

**Key properties:**
- Context is set once at the start of `syncTenant()` and is read-only downstream — no mutation concerns
- Similar to NestJS `ClsModule` / request-scoped context in HTTP servers
- Works with `Map<Class, Instance>` indexing for typed service retrieval (e.g., `tenant.get(Logger)`) if needed later
- Services remain NestJS singletons — only the tenant context varies per execution

**Changes to existing modules:**

- `AppModule` removes `confluenceConfig`, `uniqueConfig`, `processingConfig` from `ConfigModule.forRoot` load array (tenant config is no longer global)
- `ConfluenceAuthModule` is removed — `TenantAuthFactory` replaces the singleton auth wiring
- `ConfluenceAuthenticationService` is removed — its logic moves into `TenantAuthFactory`
- Auth strategy classes (`OAuth2LoAuthStrategy`, `PatAuthStrategy`) and `TokenCache` remain unchanged
- `getFirstTenantConfig()` and the singleton `registerAs` exports are removed

#### Layer 3: Scheduler

```typescript
@Injectable()
export class TenantSyncScheduler implements OnModuleInit {
  private readonly logger = new Logger(TenantSyncScheduler.name);

  constructor(
    private readonly tenantRegistry: TenantRegistry,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {}

  onModuleInit() {
    for (const tenant of this.tenantRegistry.getAll()) {
      const cronExpression = tenant.config.processing.scanIntervalCron;
      const job = new CronJob(cronExpression, () => this.syncTenant(tenant));
      this.schedulerRegistry.addCronJob(`sync:${tenant.name}`, job);
      job.start();
      tenant.logger.log(`Scheduled sync with cron: ${cronExpression}`);
    }
  }

  private async syncTenant(tenant: TenantContext): Promise<void> {
    if (tenant.isScanning) {
      tenant.logger.log('Sync already in progress, skipping');
      return;
    }
    tenant.isScanning = true;
    try {
      // Set AsyncLocalStorage context for downstream access
      await tenantStorage.run(tenant, async () => {
        tenant.logger.log('Starting sync');
        const token = await tenant.auth.getAccessToken();
        tenant.logger.log('Token acquired successfully');
        // TODO: Full sync pipeline
      });
    } catch (error) {
      tenant.logger.error('Sync failed', { error });
    } finally {
      tenant.isScanning = false;
    }
  }
}
```

Per-tenant cron jobs are registered dynamically via NestJS `SchedulerRegistry` since each tenant can have its own `scanIntervalCron`.

#### Layer 5: Observability

**Logging — per-service AND per-tenant:**

Logs should include both the service name (e.g., `TenantSyncScheduler`) and the tenant name (e.g., `acme`) so they are independently filterable in Grafana/log aggregation.

For this ticket, start with a simple combined NestJS Logger context string:

```typescript
// In TenantContext — a base logger scoped to the tenant
const logger = new Logger(`Tenant:${name}`);

// In downstream services — can further scope
tenant.logger.log('Starting sync'); // context: "Tenant:acme"
```

```json
{"level":"info", "context":"Tenant:acme", "msg":"Starting sync"}
{"level":"error", "context":"Tenant:acme", "msg":"Sync failed", "error":"..."}
```

**Future improvement:** Evolve to pino child loggers that add `tenantName` as a dedicated structured JSON field (via `pinoLogger.child({ tenantName: 'acme' })`). This would be retrieved from `AsyncLocalStorage`, enriching any service-scoped logger with the current tenant context automatically. The NestJS Logger context string approach is sufficient for the initial implementation.

- All downstream operations use `tenant.logger` — logs automatically include the tenant context string
- **Metrics:** Should carry a `tenant` label, leveraging `AsyncLocalStorage` for automatic scoping. Deferred to a later ticket — not in scope here.
- **OpenTelemetry spans:** `@Span` decorators (as used in SPC) are also deferred. Focus on getting the multi-tenancy foundation working first.

### Error Handling

**Config loading errors:**
- Missing `os.environ/` variable → the env resolver returns an empty string; the Zod schema decides if this is an error (required fields fail with standard Zod "string must be at least 1 character" errors, optional fields accept it)
- Invalid YAML → fail-fast at startup with file path in error message
- Invalid tenant name (characters/format) → fail-fast at startup as misconfiguration
- Duplicate tenant names → fail-fast at startup as misconfiguration
- `inactive` tenant → config validated but tenant not registered, logged as info
- `deleted` tenant → config NOT validated, tenant not registered, logged as info
- Zero `active` tenants → fail-fast at startup

**Scheduler errors:**
- Per-tenant `try/catch` — one tenant failure does not affect others
- Token acquisition failure → logged with `tenantName` context, tenant skipped this cycle
- `tenant.isScanning` flag prevents overlapping syncs per tenant

**Secret handling:**
- `os.environ/` resolution defaults to `Redacted` wrapping via `envResolvableRedactedStringSchema` — env-loaded fields are secrets by default
- Explicit `envResolvablePlainStringSchema` opt-out required for the rare non-secret env reference
- The env resolver itself does not validate — it resolves the reference and returns the value (or empty string). The Zod schema (required/optional, min length) decides whether a missing value is an error
- `Redacted` wrapper prevents secrets from appearing in logs/errors (unchanged from current)

### Testing Strategy

- **Config loader tests** — extend existing `tenant-config-loader.spec.ts`:
  - `os.environ/` resolution (happy path + missing env var → empty string returned to schema)
  - Tenant name extraction from filename
  - Tenant name validation: valid names pass, invalid characters rejected, duplicates rejected
  - `status: inactive` skipping (config validated, tenant not registered)
  - `status: deleted` skipping (config not validated, tenant not registered)
  - Default status is `active` when field is omitted
  - Multi-tenant loading with different auth modes
  - Backward compatibility: plain string values still work (non-`os.environ/` fields are unaffected)
- **Zod schema tests** — test `envResolvableRedactedStringSchema` (Redacted by default) and `envResolvablePlainStringSchema` (explicit opt-out) in isolation
- **TenantRegistry tests** — construction from multiple configs, `get()`, `getAll()`, token acquisition delegation, unknown tenant error
- **AsyncLocalStorage tests** — context is set during sync execution, context is accessible in downstream calls, error thrown when accessed outside of sync execution
- **Scheduler tests** — parallel execution, `tenant.isScanning` prevents duplicate syncs, error isolation between tenants, per-tenant cron registration
- **Existing auth tests** — unchanged (strategies and token cache are reused as-is)

## Out of Scope

- Confluence API client (pages, labels, content fetching)
- Unique API client (ingestion, scope management)
- Per-tenant rate limiters (Bottleneck) — future architecture: Confluence rate limiter per-tenant, Unique rate limiter global shared; potential optimization to detect tenants sharing the same Confluence instance
- Processing pipeline (page scanning, content extraction, ingestion)
- Helm chart multi-tenant changes (env var template per tenant)
- Per-tenant metrics labels (deferred — will leverage AsyncLocalStorage)
- OpenTelemetry `@Span` decorators (deferred — add after foundation is working)
- Pino child logger evolution for dedicated `tenantName` JSON fields (start simple, improve later)

When these layers are implemented, `TenantContext` will expand to include them:

```typescript
// Future TenantContext (illustrative, not part of this ticket)
interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  readonly auth: TenantAuth;
  readonly confluenceClient: ConfluenceApiClient;   // via ConfluenceClientFactory
  readonly uniqueClient: UniqueApiClient;            // via UniqueClientFactory
  readonly confluenceRateLimiter: Bottleneck;        // via RateLimiterFactory (per-tenant — each tenant may hit different instance)
  readonly uniqueRateLimiter: Bottleneck;            // via RateLimiterFactory (global shared — all tenants share same Unique platform)
  isScanning: boolean;
}
```

The scheduler's `syncTenant()` would then use these directly:

```typescript
async syncTenant(tenant: TenantContext) {
  const pages = await tenant.confluenceClient.getLabeledPages('ai-ingest');
  for (const page of pages) {
    const content = await tenant.confluenceClient.getPageContent(page.id);
    await tenant.uniqueClient.ingest(content);
  }
}
```

## Tasks

1. **Create `envResolvableSchema` Zod utilities** — Add `envResolvableRedactedStringSchema` (Redacted by default) and `envResolvablePlainStringSchema` (explicit opt-out for non-secrets) to `zod.util.ts`. The env resolver returns empty string for missing env vars (schema decides if it's an error via required/optional). Update `confluence.schema.ts` and `unique.schema.ts` to use the new schemas for secret fields. Remove `injectSecretsFromEnvironment()` from `tenant-config-loader.ts`.

2. **Add tenant name extraction, validation, and status field to config loader** — `getTenantConfigs()` returns `NamedTenantConfig[]` with name derived from filename. Validate tenant names with regex `^[a-z0-9]+(-[a-z0-9]+)*$` and reject duplicates (fail-fast). Support top-level `status` field (`active` | `inactive` | `deleted`, default `active`). `inactive` tenants are validated but skipped; `deleted` tenants skip validation entirely. Remove `getFirstTenantConfig()` and the singleton `registerAs` exports. Update tests.

3. **Create TenantAuth, TenantContext, TenantAuthFactory, and TenantRegistry** — Define `TenantAuth` interface with `getAccessToken()`. Define `TenantContext` with `name`, `config`, `logger`, `auth`, `isScanning`. Create `TenantAuthFactory` (NestJS injectable) with `create(config)` returning a `TenantAuth`. Create `TenantRegistry` as a thin orchestrator that injects the factory and assembles contexts (clients created once and cached). Create `TenantModule`.

4. **Implement AsyncLocalStorage for tenant context propagation** — Create `tenantStorage` (`AsyncLocalStorage<TenantContext>`) and `getCurrentTenant()` helper. The scheduler sets context via `tenantStorage.run()` at the start of each sync. Downstream services retrieve the current tenant implicitly.

5. **Remove ConfluenceAuthModule and update AppModule** — Remove `ConfluenceAuthModule` and `ConfluenceAuthenticationService` (role replaced by `TenantAuthFactory`). Update `AppModule` to import `TenantModule` instead. Remove tenant config from `ConfigModule.forRoot` load array. Keep auth strategy classes and `TokenCache` unchanged.

6. **Implement TenantSyncScheduler** — Create `SchedulerModule` with `TenantSyncScheduler`. Register per-tenant cron jobs dynamically via `SchedulerRegistry`. Use `tenant.isScanning` flag to prevent overlapping syncs. Set `AsyncLocalStorage` context at the start of each sync. Sync action: acquire token and log success/failure. Add `@nestjs/schedule` dependency.

7. **Update local tenant config and .env for os.environ/ pattern** — Update `local-tenant-config.yaml` to use `os.environ/` references for secrets. Update `.env.example` and `.env` with the new variable naming convention.
