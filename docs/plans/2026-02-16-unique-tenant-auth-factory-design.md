# Design: UniqueTenantAuthFactory + TenantServiceRegistry

## Problem

The confluence-connector has `ConfluenceTenantAuthFactory` for Confluence source auth, but no equivalent for Unique/Zitadel service auth. When the sync pipeline calls Unique APIs (ingestion, scope management), it needs per-tenant authenticated HTTP headers. The `UniqueConfig` schema already models two modes (`cluster_local` and `external`), but there is no factory to produce per-tenant auth from this config.

Additionally, as the number of per-tenant services grows (logger, Confluence auth, Unique auth, future API clients), the flat `TenantContext` interface becomes unwieldy. The agreed architecture direction is a service container pattern — a `Map<Class, Instance>` approach where per-tenant dependencies are stored in a typed container and retrieved via `AsyncLocalStorage`.

## Solution

### Overview

Two interconnected changes:

1. **`UniqueTenantAuthFactory`** — creates a `UniqueServiceAuth` object per tenant from `UniqueConfig`. Supports both `cluster_local` (static headers) and `external` (Zitadel OAuth client-credentials with token caching). Uses undici with retry/redirect interceptors for the Zitadel token request, matching the sharepoint-connector pattern.

2. **`TenantServiceRegistry`** — a typed service container keyed by abstract class constructors. Services that need to be stored in the container (`TenantAuth`, `UniqueServiceAuth`) are promoted from interfaces to abstract classes so they exist at runtime and can serve as map keys. Stored on `TenantContext`, initialized per tenant by `TenantRegistry`, and accessible downstream via `AsyncLocalStorage`.

### Architecture

#### UniqueServiceAuth Abstract Class

```typescript
export abstract class UniqueServiceAuth {
  abstract getHeaders(): Promise<Record<string, string>>;
}
```

Using an abstract class instead of an interface so it exists at runtime and can be used as a `TenantServiceRegistry` map key.

Consumers spread headers without caring about auth mode — same pattern as sharepoint-connector's `IngestionHttpClient.getHeaders()` and teams-mcp's `getAuthHeaders()`.

#### UniqueTenantAuthFactory

```
UniqueTenantAuthFactory
├── create(uniqueConfig: UniqueConfig) → UniqueServiceAuth
│
├── cluster_local mode → ClusterLocalAuthStrategy
│     └── getHeaders() → { 'x-company-id', 'x-user-id', 'x-service-id' }
│
└── external mode → ZitadelAuthStrategy
      ├── undici dispatcher with default retry and redirect interceptors
      ├── client-credentials grant to Zitadel token endpoint (Basic auth)
      ├── TokenCache for caching + request deduplication
      └── getHeaders() → { Authorization: 'Bearer <token>' }
```

- `ClusterLocalAuthStrategy`: synchronous, returns static headers from config. No network calls.
- `ZitadelAuthStrategy`: same logic as sharepoint-connector's `UniqueAuthService` (client-credentials grant, Basic auth, `application/x-www-form-urlencoded` body with scope+grant_type), but uses the existing `TokenCache` class instead of inline caching. `TokenCache` provides request deduplication (concurrent calls share the same in-flight promise) and expiration-aware caching — already proven by `ConfluenceTenantAuthFactory`. Uses undici `interceptors.retry()` and `interceptors.redirect()` with default config for resilience. Designed so swapping to the future shared Unique auth library is a minimal change.

#### TenantAuth Abstract Class

The existing `TenantAuth` interface is promoted to an abstract class for the same reason:

```typescript
export abstract class TenantAuth {
  abstract getAccessToken(): Promise<string>;
}
```

All other interfaces in the codebase remain interfaces — only services that need to be stored in the container are promoted.

#### TenantServiceRegistry

A typed container keyed by abstract class constructors:

```typescript
type AbstractClass<T> = abstract new (...args: unknown[]) => T;

class TenantServiceRegistry {
  private readonly map = new Map<Function, unknown>();

  set<T>(key: AbstractClass<T>, instance: T): this;
  get<T>(key: AbstractClass<T>): T;       // throws if not found
  has<T>(key: AbstractClass<T>): boolean;
}
```

No tokens, no symbols — the abstract class itself is the key. TypeScript infers the return type from the class generic.

#### `getTenantService` Helper

Top-level helper that reads the current tenant from `AsyncLocalStorage` and retrieves a service from the registry:

```typescript
export function getTenantService<T>(key: AbstractClass<T>): T {
  return getCurrentTenant().services.get(key);
}
```

Lives alongside `getCurrentTenant` and `getTenantLogger` in the tenant module. Usage:

```typescript
const auth = getTenantService(UniqueServiceAuth);
const headers = await auth.getHeaders();
```

#### Updated TenantContext

```typescript
export interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly services: TenantServiceRegistry;
  // Logger stays as a flat field — pino's Logger type is external
  // and getTenantLogger() already provides service-scoped access.
  readonly logger: Logger;
  isScanning: boolean;
}
```

Auth services (`TenantAuth`, `UniqueServiceAuth`) move into `services`. The logger stays as a flat field because pino's `Logger` is an external type we don't control, and `getTenantLogger()` already provides the right abstraction with service-scoped child loggers.

#### Updated TenantRegistry Wiring

```typescript
onModuleInit(): void {
  for (const { name, config } of getTenantConfigs()) {
    const tenantLogger = PinoLogger.root.child({ tenantName: name });

    const services = new TenantServiceRegistry()
      .set(TenantAuth, this.confluenceAuthFactory.create(config.confluence))
      .set(UniqueServiceAuth, this.uniqueAuthFactory.create(config.unique));

    this.tenants.set(name, {
      name, config, services,
      logger: tenantLogger,
      isScanning: false,
    });
  }
}
```

### Error Handling

- **ZitadelAuthStrategy**: logs structured errors via `sanitizeError()` before rethrowing. Undici default retry interceptor handles transient network failures. `TokenCache` clears on failure so the next call retries.
- **ClusterLocalAuthStrategy**: synchronous, no network calls. Can only fail if config is invalid (caught at config-load time by Zod validation).
- **UniqueTenantAuthFactory**: exhaustive switch on `serviceAuthMode` — throws domain-qualified error for unsupported modes.
- **TenantServiceRegistry.get()**: throws descriptive error with class name when service not found.
- **TokenCache**: clears cached promise on failure so the next sync attempt retries. Deduplicates concurrent token requests.

### Testing Strategy

- **TenantServiceRegistry**: unit tests for `set/get/has`, abstract class keys, type safety, error on missing service.
- **ZitadelAuthStrategy**: unit tests with mocked undici dispatcher. Verifies correct request shape (URL, Basic auth header, URL-encoded body with scope), token parsing, error handling, and caching via TokenCache.
- **ClusterLocalAuthStrategy**: unit tests verifying correct header construction from both `cluster_local` config shapes.
- **UniqueTenantAuthFactory**: unit tests verifying correct strategy selection based on `serviceAuthMode`.
- **TenantRegistry**: update existing tests to verify both `TenantAuth` and `UniqueServiceAuth` are registered in the `services` container.

## Out of Scope

- **Rate limiting for Unique API**: shared across tenants (detail for later).
- **Proxy support**: not needed now, undici client is minimal.
- **OpenTelemetry/tracing**: add once the core sync pipeline is running.
- **Full AsyncLocalStorage-based service injection**: current helper functions (`getTenantService`, `getTenantLogger`) are sufficient.

## Tasks

1. **Create `TenantServiceRegistry` and `getTenantService` helper** — typed container keyed by abstract class constructors, with `set/get/has` methods. Add `getTenantService<T>(key)` top-level helper alongside `getCurrentTenant` and `getTenantLogger`. Include unit tests.

2. **Promote `TenantAuth` to abstract class and create `UniqueServiceAuth` abstract class with strategy implementations** — convert `TenantAuth` from interface to abstract class, create `UniqueServiceAuth` abstract class with `getHeaders()`, implement `ClusterLocalAuthStrategy` (static headers from config) and `ZitadelAuthStrategy` (undici-based client-credentials flow with `TokenCache`, same logic as sharepoint-connector's `UniqueAuthService`). Update all consumers of the old `TenantAuth` interface. Include unit tests for both strategies.

3. **Create `UniqueTenantAuthFactory`** — factory that selects strategy based on `serviceAuthMode`, with exhaustive switch. Include unit tests.

4. **Update `TenantContext` and `TenantRegistry`** — add `services: TenantServiceRegistry` to `TenantContext`, remove flat `auth` field (replaced by `services.get(TenantAuth)`). Update `TenantRegistry.onModuleInit()` to wire both factories and populate the container. Update all existing consumers and tests.

5. **Update `TenantModule` providers** — register `UniqueTenantAuthFactory` in the module's providers array.
