# @unique-ag/unique-api

Shared NestJS module for Unique platform API integration. Provides a typed client for GraphQL and HTTP interactions with scope management, file ingestion, users, and groups services — with built-in authentication, rate limiting, and OpenTelemetry observability.

## Package structure

```
src/
├── core/                          # Module wiring, factory, registry, types
│   ├── unique-api.module.ts       # NestJS dynamic module (forRoot / forFeature)
│   ├── unique-api-client.factory.ts  # Assembles fully-wired client instances
│   ├── unique-api-client.registry.ts # Manages named clients with lifecycle
│   ├── types.ts                   # Public types and interfaces
│   ├── tokens.ts                  # DI tokens
│   ├── observability.ts           # OTel metric definitions
│   └── batch-processor.service.ts # Batch processing utility
├── auth/
│   └── unique-auth.ts             # Token caching (cluster_local + external/Zitadel)
├── clients/
│   ├── unique-graphql.client.ts   # GraphQL transport (graphql-request + Bottleneck)
│   └── ingestion-http.client.ts   # HTTP transport (undici + Bottleneck)
├── scopes/                        # Scope management (queries + service)
├── files/                         # File/content management (queries + service)
├── users/                         # User queries + service
├── groups/                        # Group management (queries + service)
└── ingestion/                     # File ingestion and diff (queries + service)
```

## Usage

### Basic setup

```typescript
import { Module } from '@nestjs/common';
import { UniqueApiModule } from '@unique-ag/unique-api';

@Module({
  imports: [
    UniqueApiModule.forRoot({
      observability: {
        metricPrefix: 'spc_unique',
        loggerContext: 'UniqueApi',
      },
    }),
  ],
})
export class AppModule {}
```

### Async setup (config from environment)

```typescript
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { UniqueApiModule } from '@unique-ag/unique-api';

@Module({
  imports: [
    ConfigModule.forRoot(),
    UniqueApiModule.forRootAsync({
      imports: [ConfigModule],
      inject: [ConfigService],
      useFactory: (config: ConfigService) => ({
        observability: {
          metricPrefix: config.get('METRIC_PREFIX', 'unique_api'),
        },
      }),
    }),
  ],
})
export class AppModule {}
```

### Static named client (forFeature)

Register a client at bootstrap time when config is known upfront:

```typescript
import { Module, Injectable, Inject } from '@nestjs/common';
import {
  UniqueApiModule,
  UniqueApiClient,
  getUniqueApiClientToken,
} from '@unique-ag/unique-api';

@Module({
  imports: [
    UniqueApiModule.forRoot(),
    UniqueApiModule.forFeature('sharepoint', {
      auth: {
        mode: 'cluster_local',
        serviceId: 'sharepoint-connector',
        extraHeaders: { 'x-unique-company-id': '...' },
      },
      endpoints: {
        scopeManagementBaseUrl: 'http://scope-management:3000',
        ingestionBaseUrl: 'http://node-ingestion:3000',
      },
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

  async syncScopes() {
    const scopes = await this.uniqueApi.scopes.listChildren('root-id');
    const users = await this.uniqueApi.users.listAll();
    // ...
  }
}
```

### Async named client (forFeatureAsync)

```typescript
UniqueApiModule.forFeatureAsync('sharepoint', {
  imports: [ConfigModule],
  inject: [ConfigService],
  useFactory: (config: ConfigService) => ({
    auth: {
      mode: 'external' as const,
      zitadelOauthTokenUrl: config.getOrThrow('ZITADEL_TOKEN_URL'),
      zitadelClientId: config.getOrThrow('ZITADEL_CLIENT_ID'),
      zitadelClientSecret: config.getOrThrow('ZITADEL_CLIENT_SECRET'),
      zitadelProjectId: config.getOrThrow('ZITADEL_PROJECT_ID'),
    },
    endpoints: {
      scopeManagementBaseUrl: config.getOrThrow('SCOPE_MANAGEMENT_URL'),
      ingestionBaseUrl: config.getOrThrow('INGESTION_URL'),
    },
  }),
});
```

### Runtime multi-tenant (registry)

For scenarios where tenant configs are unknown at bootstrap:

```typescript
import { Injectable, Inject } from '@nestjs/common';
import {
  UNIQUE_API_CLIENT_REGISTRY,
  UniqueApiClientRegistry,
  UniqueApiClientConfig,
} from '@unique-ag/unique-api';

@Injectable()
export class TenantService {
  constructor(
    @Inject(UNIQUE_API_CLIENT_REGISTRY)
    private readonly registry: UniqueApiClientRegistry,
  ) {}

  async processForTenant(tenantKey: string, config: UniqueApiClientConfig) {
    const client = await this.registry.getOrCreate(tenantKey, config);
    const files = await client.files.getByKeyPrefix(`tenant/${tenantKey}`);
    // ...
  }

  async removeTenant(tenantKey: string) {
    await this.registry.delete(tenantKey);
  }
}
```

## Authentication modes

- **`cluster_local`** — Header-based auth for in-cluster communication. Sends `x-service-id` and any extra headers.
- **`external`** — OAuth client_credentials flow via Zitadel. Tokens are cached per-client and refreshed automatically on expiry.

## Observability

- **Logging** — Uses NestJS `Logger` with configurable context.
- **Metrics** — OpenTelemetry counters and histograms:
  - `<prefix>_requests_total` — total API requests
  - `<prefix>_errors_total` — total errors
  - `<prefix>_request_duration_ms` — request latency histogram
  - `<prefix>_slow_requests_total` — slow request counter by duration bucket
  - `<prefix>_auth_token_refresh_total` — token refresh counter
