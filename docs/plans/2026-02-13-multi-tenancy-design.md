# Design: Multi-Tenancy Foundation

**Ticket:** UN-17171 | **ADR:** [Confluence Connector Multi-Tenancy Architecture](https://unique-ch.atlassian.net/wiki/spaces/ptf/pages/1906737185)

## Problem

The confluence-connector operates in single-tenant mode: it reads the first tenant config file, registers it globally via NestJS `ConfigModule`, and creates a single auth strategy. All env var secrets (`CONFLUENCE_CLIENT_SECRET`, `CONFLUENCE_PAT`, `ZITADEL_CLIENT_SECRET`) are global — different credentials per tenant are not supported.

## Solution

### Overview

Transform the connector to support multiple Confluence tenants from a single deployment across four layers:

1. **Config & Secrets (Layer 1):** Replace the implicit secret injection (`injectSecretsFromEnvironment`) with LiteLLM-style `os.environ/VAR_NAME` references in tenant YAML. Secrets are resolved inside Zod transforms during validation. Tenant name is derived from the filename. An optional `enabled` field (defaults to `true`) lets operators disable a tenant without removing its config file.

2. **TenantRegistry (Layer 2):** A global `TenantRegistry` service holds a `Map<string, TenantContext>`. Each `TenantContext` bundles the tenant's config, a pre-configured auth strategy with its own `TokenCache`, and a child logger with `tenantName` context. This replaces the current `ConfigModule.forRoot` registration of tenant-scoped config.

3. **Scheduler (Layer 3):** Each tenant gets its own `CronJob` registered dynamically at startup via NestJS `SchedulerRegistry`, using the tenant's `scanIntervalCron` expression. Each `TenantContext` carries an `isScanning` flag so overlapping cron ticks for the same tenant are skipped. For this ticket, the sync action acquires an auth token per tenant (proving per-tenant auth works end-to-end).

4. **Observability (Layer 5):** Every `TenantContext` includes a child logger (`Logger` with `tenantName` context). All log lines during a tenant sync include `tenantName` as a structured field.

### Key Decisions

#### Decision 1: Auth wiring — combined TenantContext vs separate ConfluenceAuthModule

**Option A (chosen): Combined TenantContext with `getAccessToken()` baked in.**
`TenantRegistry` creates per-tenant auth strategies and token caches at startup, exposing a single `getAccessToken()` closure on `TenantContext`. `ConfluenceAuthModule` and `ConfluenceAuthenticationService` are removed — their role is absorbed by the registry. Consumers get a `TenantContext` and call `tenant.getAccessToken()` directly.

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
┌─────────────────────────────────────────────────────┐
│ AppModule                                           │
│                                                     │
│  ConfigModule.forRoot (app-level config only)       │
│  TenantModule (global)                              │
│    └─ TenantRegistry                                │
│         └─ Map<string, TenantContext>                │
│              ├─ name, config, logger, isScanning     │
│              └─ getAccessToken()                     │
│  SchedulerModule                                    │
│    └─ TenantSyncScheduler                           │
│  LoggerModule, ProbeModule, OpenTelemetryModule      │
└─────────────────────────────────────────────────────┘
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

// Base: resolves os.environ/ references to actual env var values
const envResolvableStringSchema = z.string().transform((val, ctx) => {
  if (!val.startsWith(ENV_REF_PREFIX)) return val;
  const varName = val.slice(ENV_REF_PREFIX.length);
  const resolved = process.env[varName];
  if (!resolved) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: `Environment variable '${varName}' is not set (referenced as '${val}')`,
    });
    return z.NEVER;
  }
  return resolved;
});

// For secret fields: resolve env ref, then wrap in Redacted
const envResolvableRedactedStringSchema = envResolvableStringSchema
  .pipe(z.string().min(1))
  .transform((val) => new Redacted(val));
```

**The `injectSecretsFromEnvironment()` function is removed entirely.** The YAML is the single source of truth for which env var each field reads from.

**Tenant name extraction:**

| Filename | Tenant Name |
| --- | --- |
| `default-tenant-config.yaml` | `default` |
| `acme-tenant-config.yaml` | `acme` |
| `acme-corp-tenant-config.yaml` | `acme-corp` |

Rule: strip the `-tenant-config.yaml` suffix from the filename (without directory path).

**Tenant disabling:** An optional top-level `enabled` field (defaults to `true`). Tenants with `enabled: false` are logged and skipped before validation:

```yaml
enabled: false  # This tenant is temporarily disabled
confluence:
  # ... (may contain errors, won't be validated)
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

A global NestJS provider holding all tenant contexts:

```typescript
interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  isScanning: boolean;
  getAccessToken(): Promise<string>;
  // TODO: Add per-tenant Confluence API client
  // TODO: Add per-tenant Unique API client
  // TODO: Add per-tenant rate limiters
}

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly tenants = new Map<string, TenantContext>();

  onModuleInit() {
    const configs = getTenantConfigs();
    for (const { name, config } of configs) {
      const authStrategy = createAuthStrategy(config.confluence);
      const tokenCache = new TokenCache();
      const logger = new Logger(`Tenant:${name}`);

      this.tenants.set(name, {
        name,
        config,
        logger,
        isScanning: false,
        getAccessToken: () => tokenCache.getToken(() => authStrategy.acquireToken()),
      });

      logger.log('Tenant registered');
    }
  }

  get(name: string): TenantContext { ... }
  getAll(): TenantContext[] { ... }
  get size(): number { ... }
}
```

**Changes to existing modules:**

- `AppModule` removes `confluenceConfig`, `uniqueConfig`, `processingConfig` from `ConfigModule.forRoot` load array (tenant config is no longer global)
- `ConfluenceAuthModule` is removed — auth strategy creation moves into `TenantRegistry`
- `ConfluenceAuthenticationService` is removed — `TenantContext.getAccessToken()` replaces it
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
      tenant.logger.log('Starting sync');
      const token = await tenant.getAccessToken();
      tenant.logger.log('Token acquired successfully');
      // TODO: Full sync pipeline
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

Each `TenantContext` holds a NestJS `Logger` scoped to the tenant:

```typescript
const logger = new Logger(`Tenant:${name}`);
```

NestJS `Logger` accepts a context string in the constructor. This context is included in every log line automatically via `nestjs-pino`:

```json
{"level":"info", "context":"Tenant:acme", "msg":"Starting sync"}
{"level":"error", "context":"Tenant:acme", "msg":"Sync failed", "error":"..."}
```

This is **not** a pino child logger (which would add `tenantName` as a separate structured field via `pinoLogger.child({ tenantName: 'acme' })`). The NestJS `Logger` approach is simpler and consistent with how logging works throughout the codebase (e.g., `new Logger(SchedulerService.name)` in SPC). The context string `"Tenant:acme"` is filterable in log aggregation tools.

If deeper structured logging is needed later (e.g., a dedicated `tenantName` JSON field for dashboards), we can switch to pino child loggers — but that requires accessing the underlying pino instance, which adds complexity. The NestJS Logger context is sufficient for this ticket.

- All downstream operations use `tenant.logger` — logs automatically include the tenant context string
- Future: When metrics are added, they should carry a `tenant` label

### Error Handling

**Config loading errors:**
- Missing `os.environ/` variable → Zod validation error with full path (e.g., `confluence.auth.clientSecret: Environment variable 'ACME_SECRET' is not set`)
- Invalid YAML → fail-fast at startup with file path in error message
- `enabled: false` tenant → logged as info and skipped, not an error
- Zero enabled tenants → fail-fast at startup

**Scheduler errors:**
- Per-tenant `try/catch` — one tenant failure does not affect others
- Token acquisition failure → logged with `tenantName` context, tenant skipped this cycle
- `tenant.isScanning` flag prevents overlapping syncs per tenant

**Secret handling:**
- `Redacted` wrapper prevents secrets from appearing in logs/errors (unchanged from current)
- `os.environ/` resolution inside Zod means unresolved refs fail with clear messages and full field paths

### Testing Strategy

- **Config loader tests** — extend existing `tenant-config-loader.spec.ts`:
  - `os.environ/` resolution (happy path + missing env var)
  - Tenant name extraction from filename
  - `enabled: false` skipping
  - Multi-tenant loading with different auth modes
  - Backward compatibility: plain string values still work (for non-secret fields)
- **Zod schema tests** — test `envResolvableStringSchema` and `envResolvableRedactedStringSchema` in isolation
- **TenantRegistry tests** — construction from multiple configs, `get()`, `getAll()`, token acquisition delegation, unknown tenant error
- **Scheduler tests** — parallel execution, `tenant.isScanning` prevents duplicate syncs, error isolation between tenants, per-tenant cron registration
- **Existing auth tests** — unchanged (strategies and token cache are reused as-is)

## Out of Scope

- Confluence API client (pages, labels, content fetching)
- Unique API client (ingestion, scope management)
- Per-tenant rate limiters (Bottleneck)
- Processing pipeline (page scanning, content extraction, ingestion)
- Helm chart multi-tenant changes (env var template per tenant)
- Per-tenant metrics labels

When these layers are implemented, `TenantContext` will expand to include them:

```typescript
// Future TenantContext (illustrative, not part of this ticket)
interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  getAccessToken(): Promise<string>;
  readonly confluenceClient: ConfluenceApiClient;   // pre-configured with baseUrl + auth
  readonly uniqueClient: UniqueApiClient;            // pre-configured with baseUrl + auth
  readonly confluenceRateLimiter: Bottleneck;        // per-tenant, from config.confluence.apiRateLimitPerMinute
  readonly uniqueRateLimiter: Bottleneck;            // global shared instance (per ADR reviewer feedback)
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

1. **Create `envResolvableStringSchema` Zod utilities** — Add `envResolvableStringSchema` and `envResolvableRedactedStringSchema` to `zod.util.ts`. Update `confluence.schema.ts` and `unique.schema.ts` to use them for secret fields. Remove `injectSecretsFromEnvironment()` from `tenant-config-loader.ts`.

2. **Add tenant name extraction and enabled flag to config loader** — `getTenantConfigs()` returns `NamedTenantConfig[]` with name derived from filename. Support optional top-level `enabled` field (default `true`). Remove `getFirstTenantConfig()` and the singleton `registerAs` exports. Update tests.

3. **Create TenantContext interface and TenantRegistry service** — Define `TenantContext` with `name`, `config`, `logger`, `getAccessToken()`. Create `TenantRegistry` as a global provider that builds the tenant map at startup, creating per-tenant auth strategies and token caches. Create `TenantModule`.

4. **Remove ConfluenceAuthModule and update AppModule** — Remove `ConfluenceAuthModule` and `ConfluenceAuthenticationService` (role absorbed by `TenantRegistry`). Update `AppModule` to import `TenantModule` instead. Remove tenant config from `ConfigModule.forRoot` load array. Keep auth strategy classes and `TokenCache` unchanged.

5. **Implement TenantSyncScheduler** — Create `SchedulerModule` with `TenantSyncScheduler`. Register per-tenant cron jobs dynamically via `SchedulerRegistry`. Use `tenant.isScanning` flag to prevent overlapping syncs. Sync action: acquire token and log success/failure. Add `@nestjs/schedule` dependency.

6. **Update local tenant config and .env for os.environ/ pattern** — Update `local-tenant-config.yaml` to use `os.environ/` references for secrets. Update `.env.example` and `.env` with the new variable naming convention.
