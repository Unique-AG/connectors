# Design: Extract Unique API Services into Shared NestJS Package

## Problem

The Unique API integration code (GraphQL client, authentication, and domain services for scopes/files/users/groups/ingestion) is embedded in `sharepoint-connector` and duplicated in simpler forms across `teams-mcp` and `outlook-semantic-mcp`. Key issues:

1. **Code duplication** - auth flow, API patterns, DTOs, and retries are repeated.
2. **Static singleton coupling** - existing NestJS singletons are tied to app boot config and do not support dynamic tenant/client creation.
3. **Inconsistent observability** - logging and metrics differ by service and are easy to miss.
4. **No standard reuse path** - new connectors must copy and adapt implementation details.

## Solution

### Overview

Create a `@unique-ag/unique-api` package in `packages/unique-api/` as a NestJS-first module that provides:

1. **A dynamic NestJS module** (`UniqueApiModule.forRoot(...)` / `forRootAsync(...)`) as the primary integration path.
2. **Built-in observability** using NestJS logging and OpenTelemetry metrics baked into the package.
3. **Runtime multi-client support** via `UniqueApiClientFactory` and `UniqueApiClientRegistry`, so clients can be created on demand for unknown tenants.
4. **Per-client isolated state** (auth token cache, GraphQL clients, optional rate limiter).
5. **Minimal public surface** with NestJS module APIs and stable client-facing contracts only.

`forFeature(...)` remains available for known static clients at bootstrap, while runtime flows use the registry.

### Architecture

**Package structure (feature-based with colocated tests):**

```
packages/unique-api/
├── src/
│   ├── index.ts
│   ├── core/
│   │   ├── types.ts
│   │   ├── tokens.ts
│   │   ├── unique-api.module.ts
│   │   ├── unique-api-client.factory.ts
│   │   ├── unique-api-client.registry.ts
│   │   └── batch-processor.service.ts
│   ├── clients/
│   │   ├── unique-graphql.client.ts
│   │   └── ingestion-http.client.ts
│   ├── auth/
│   │   ├── unique-auth.ts
│   │   └── unique-auth.spec.ts
│   ├── scopes/
│   │   ├── scopes.queries.ts
│   │   ├── scopes.service.ts
│   │   └── scopes.service.spec.ts
│   ├── files/
│   │   ├── files.queries.ts
│   │   ├── files.service.ts
│   │   └── files.service.spec.ts
│   ├── users/
│   │   ├── users.queries.ts
│   │   ├── users.service.ts
│   │   └── users.service.spec.ts
│   ├── groups/
│   │   ├── groups.queries.ts
│   │   ├── groups.service.ts
│   │   └── groups.service.spec.ts
│   └── ingestion/
│       ├── ingestion.queries.ts
│       ├── file-ingestion.service.ts
│       └── file-ingestion.service.spec.ts
├── package.json
├── tsconfig.json
└── vitest.config.ts
```

### Configuration model

```typescript
interface ClusterLocalAuthConfig {
  mode: 'cluster_local';
  serviceId: string;
  extraHeaders: Record<string, string>; // includes x-company-id, x-user-id
}

interface ExternalAuthConfig {
  mode: 'external';
  zitadelOauthTokenUrl: string;
  zitadelClientId: string;
  zitadelClientSecret: string;
  zitadelProjectId: string;
}

type UniqueApiClientAuthConfig = ClusterLocalAuthConfig | ExternalAuthConfig;

interface UniqueApiClientConfig {
  auth: UniqueApiClientAuthConfig;
  endpoints: {
    scopeManagementBaseUrl: string;
    ingestionBaseUrl: string;
  };
  rateLimitPerMinute?: number;
  fetch?: typeof fetch;
  metadata?: {
    clientName?: string;
    tenantKey?: string;
  };
}

interface UniqueApiObservabilityConfig {
  loggerContext?: string; // default: UniqueApi
  metricPrefix?: string; // default: unique_api
  includeTenantDimension?: boolean; // default: false (cardinality safety)
}

interface UniqueApiModuleOptions {
  observability?: UniqueApiObservabilityConfig;
  defaultClient?: UniqueApiClientConfig; // optional static default
}
```

### Public runtime APIs

```typescript
interface UniqueApiClient {
  auth: {
    getToken(): Promise<string>;
  };
  scopes: {
    createFromPaths(paths: string[], opts?: { includePermissions?: boolean; inheritAccess?: boolean }): Promise<Scope[]>;
    getById(id: string): Promise<Scope | null>;
    getByExternalId(externalId: string): Promise<Scope | null>;
    updateExternalId(scopeId: string, externalId: string): Promise<{ id: string; externalId: string | null }>;
    updateParent(scopeId: string, newParentId: string): Promise<{ id: string; parentId: string | null }>;
    listChildren(parentId: string): Promise<Scope[]>;
    createAccesses(scopeId: string, accesses: ScopeAccess[], applyToSubScopes?: boolean): Promise<void>;
    deleteAccesses(scopeId: string, accesses: ScopeAccess[], applyToSubScopes?: boolean): Promise<void>;
    delete(scopeId: string, options?: { recursive?: boolean }): Promise<DeleteFolderResult>;
  };
  files: {
    getByKeys(keys: string[]): Promise<UniqueFile[]>;
    getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]>;
    getCountByKeyPrefix(keyPrefix: string): Promise<number>;
    move(contentId: string, newOwnerId: string, newUrl: string): Promise<ContentUpdateResult>;
    delete(contentId: string): Promise<boolean>;
    deleteByKeyPrefix(keyPrefix: string): Promise<number>;
    addAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number>;
    removeAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number>;
  };
  users: {
    listAll(): Promise<SimpleUser[]>;
    getCurrentId(): Promise<string>;
  };
  groups: {
    listByExternalIdPrefix(externalIdPrefix: string): Promise<GroupWithMembers[]>;
    create(group: { name: string; externalId: string }): Promise<GroupWithMembers>;
    update(group: { id: string; name: string }): Promise<Group>;
    delete(groupId: string): Promise<void>;
    addMembers(groupId: string, memberIds: string[]): Promise<void>;
    removeMembers(groupId: string, userIds: string[]): Promise<void>;
  };
  ingestion: {
    registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse>;
    finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }>;
    performFileDiff(fileList: FileDiffItem[], partialKey: string): Promise<FileDiffResponse>;
  };
  close?(): Promise<void>; // cleanup for shutdown/manual disposal
}

interface UniqueApiClientFactory {
  create(config: UniqueApiClientConfig): UniqueApiClient;
}

interface UniqueApiClientRegistry {
  get(key: string): UniqueApiClient | undefined;
  // Concurrent calls for the same key return the same in-flight Promise and resolve
  // to a single shared client instance (single-flight creation).
  getOrCreate(key: string, config: UniqueApiClientConfig): Promise<UniqueApiClient>;
  set(key: string, client: UniqueApiClient): void;
  delete(key: string): Promise<void>;
  clear(): Promise<void>;
}
```

### NestJS module behavior

1. `forRoot(...)` / `forRootAsync(...)` wires module-level dependencies (Nest `LoggerService`, OTel `Meter`, factory, registry).
2. `forFeature(name, config)` registers a named static client at bootstrap time (see below).
3. Runtime flows resolve clients via `UniqueApiClientRegistry.getOrCreate(tenantKey, config)`, which uses single-flight semantics so no duplicate clients are created for the same key.
4. On module shutdown, registry calls `close()` for all managed clients.

#### `forFeature` semantics

`forFeature` is a static registration path for services that know their client config at bootstrap (single-tenant connectors, dev/test setups, etc.).

```typescript
// Signature
UniqueApiModule.forFeature(name: string, config: UniqueApiClientConfig): DynamicModule

// Async variant
UniqueApiModule.forFeatureAsync(name: string, options: {
  imports?: Type[];
  inject?: InjectionToken[];
  useFactory: (...args: unknown[]) => UniqueApiClientConfig | Promise<UniqueApiClientConfig>;
}): DynamicModule
```

Behavior:

- Each `forFeature(name, config)` call creates a `UniqueApiClient` via `UniqueApiClientFactory` and registers it under the injection token `getUniqueApiClientToken(name)` (e.g., `UNIQUE_API_CLIENT_sharepoint`).
- The client is also added to the `UniqueApiClientRegistry` under the same `name` key, so runtime code can look it up via the registry if needed.
- Multiple `forFeature` calls with **different** names can coexist across importing modules.
- Calling `forFeature` with a duplicate name throws at bootstrap to prevent silent misconfiguration.
- Consumers inject the client with `@Inject(getUniqueApiClientToken('sharepoint'))`.

Example:

```typescript
@Module({
  imports: [
    UniqueApiModule.forRoot({ observability: { metricPrefix: 'spc_unique' } }),
    UniqueApiModule.forFeature('sharepoint', {
      auth: { mode: 'cluster_local', serviceId: 'sharepoint-connector', extraHeaders: { ... } },
      endpoints: { scopeManagementBaseUrl: '...', ingestionBaseUrl: '...' },
    }),
  ],
})
export class AppModule {}

@Injectable()
export class SyncService {
  constructor(
    @Inject(getUniqueApiClientToken('sharepoint'))
    private readonly uniqueApi: UniqueApiClient,
  ) {}
}
```

### Observability (baked in)

**Logging (NestJS):**

- Use Nest `LoggerService` directly in clients/services via DI.
- Structured logs at request start/end/error, auth token refresh, and retries.
- Include stable context fields: operation, target, durationMs, statusCode, retryCount, clientName.

**Metrics (OpenTelemetry):**

- Use OpenTelemetry `Meter` directly in clients/services via DI.
- Counter: `<prefix>_requests_total`
- Counter: `<prefix>_errors_total`
- Histogram: `<prefix>_request_duration_ms`
- Counter: `<prefix>_auth_token_refresh_total`
- Optional histogram: `<prefix>_payload_bytes`

Default dimensions: operation, target, result. Tenant dimension is opt-in to avoid high-cardinality issues.

### Key design decisions

1. **NestJS-first public API** - package is explicitly designed as a NestJS module.
2. **Built-in logging and metrics** - no external hooks required for baseline observability.
3. **Runtime multi-client is first-class** - registry/factory pattern supports unknown tenants at runtime.
4. **Per-client auth caching** - each client manages token lifecycle independently.
5. **Minimal exports in v1** - internals stay private until concrete reuse needs emerge.
6. **GraphQL queries stay hand-written constants** - extracted from existing `*.consts.ts`.
7. **`BatchProcessorService` moves into the package** - currently lives in `sharepoint-connector/src/shared/services/` but is only used by Unique API domain services. Extracted alongside them into `core/batch-processor.service.ts` to keep the dependency self-contained.
8. **`Smeared` type remains in `@unique-ag/utils`** - package methods continue accepting plain strings.
9. **No custom logger/OTel wrappers by default** - use Nest logger and OTel APIs directly; introduce thin utilities only if repeated boilerplate appears.

## Error Handling

- GraphQL and HTTP errors are re-thrown with operation and target context.
- Auth token acquisition failures fail fast and are logged/metriced.
- Retry policy applies only to idempotent-safe endpoints (for example file-diff).
- Domain services keep stack traces intact and avoid unnecessary wrapping.

## Testing Strategy

- **Unit tests for auth**: token caching, expiry handling, both auth modes, failures.
- **Unit tests for clients/services**: query/mutation correctness, batching behavior, retry behavior.
- **Unit tests for observability**: log emission shape and OTel instrument calls in clients/services.
- **Unit tests for registry**: `getOrCreate` concurrency (shared in-flight Promise per key), and cleanup via `close()`.
- **Module tests**: `forRootAsync` wiring and `forFeature` static client registration.
- **Integration tests** remain owned by consuming services.

## Out of Scope

- **REST Public API client** used by other services with different API surface.
- **GraphQL schema codegen**; queries remain explicit constants.
- **Migration rollout** for existing services (separate effort after package stabilization).
- **Sharepoint-specific domain constants** (source kind/name, site prefixes) owned by consumers.

## Tasks

1. **Scaffold `packages/unique-api`** following existing monorepo package conventions.
2. **Define core types** (`UniqueApiModuleOptions`, `UniqueApiClientConfig`, auth unions, domain DTOs).
3. **Define observability contract** (metric names, dimensions, log fields) and wire Nest logger + OTel meter directly through DI.
4. **Extract auth service** with per-client token cache and expiry.
5. **Extract transport clients** (`UniqueGraphqlClient`, `IngestionHttpClient`) with integrated direct logging/metrics.
6. **Extract query constants and domain services** (scopes/files/users/groups/ingestion).
7. **Implement `UniqueApiClientFactory`** to assemble fully-wired client instances.
8. **Implement `UniqueApiClientRegistry`** with single-flight `getOrCreate` and client cleanup.
9. **Implement `UniqueApiModule.forRoot/forRootAsync/forFeature`** and export factory/registry tokens.
10. **Add unit/module tests** for auth, services, observability, registry lifecycle, and DI wiring.
