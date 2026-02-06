# Design: Confluence Connector Tenant Configuration Loading

**Ticket:** UN-16933

## Problem

The Confluence Connector scaffold (UN-16932) exists but cannot connect to any external services. It needs a tenant configuration loader to:
- Read YAML config files from disk (mounted via Helm chart)
- Validate configurations against Zod schemas on startup
- Inject secrets from environment variables
- Wire up Confluence, Unique, and Processing configs in AppModule

Without this, the service starts but doesn't know how to connect to Confluence or Unique APIs.

## Solution

### Overview

Adapt the SharePoint connector's `tenant-config-loader.ts` pattern for Confluence. The loader reads a YAML config file, injects secrets from environment variables, validates against Zod schemas, and exports NestJS `registerAs` config factories.

Key components:
1. **`tenant-config-loader.ts`** - Core loader that reads YAML, injects secrets, validates schemas
2. **`processing.schema.ts`** - Confluence-specific processing configuration
3. **Updated `confluence.schema.ts`** - Full auth schema matching v1 capabilities
4. **Wiring in `AppModule`** - Load all tenant configs via ConfigModule
5. **Environment documentation** - Update `.env.example` and README

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Startup                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. main.ts bootstraps NestJS                               │
│           │                                                  │
│           ▼                                                  │
│  2. ConfigModule.forRoot loads configs:                     │
│     ├─ appConfig (from env vars)                            │
│     ├─ confluenceConfig ─┐                                  │
│     ├─ uniqueConfig ─────┼─► getTenantConfig()              │
│     └─ processingConfig ─┘         │                        │
│                                    ▼                         │
│  3. getTenantConfig():                                      │
│     ├─ Read TENANT_CONFIG_PATH_PATTERN                      │
│     ├─ Glob for matching YAML files                         │
│     ├─ Load first file (single tenant for now)              │
│     ├─ injectSecretsFromEnvironment():                      │
│     │   ├─ CONFLUENCE_API_TOKEN → cloud api_token auth      │
│     │   ├─ CONFLUENCE_PAT → onprem PAT auth                 │
│     │   ├─ CONFLUENCE_PASSWORD → onprem basic auth          │
│     │   └─ ZITADEL_CLIENT_SECRET → unique external auth     │
│     └─ Validate with TenantConfigSchema.parse()             │
│                                                              │
│  4. Services inject configs via @Inject(configToken.KEY)    │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Configuration Schemas

**Confluence Auth Schema** (matching v1 capabilities):

```typescript
// Cloud: API Token authentication
const cloudApiTokenAuth = z.object({
  mode: z.literal('api_token'),
  email: z.string().email(),
  apiToken: redactedStringSchema, // injected from CONFLUENCE_API_TOKEN
});

// On-prem: Personal Access Token
const onpremPatAuth = z.object({
  mode: z.literal('pat'),
  token: redactedStringSchema, // injected from CONFLUENCE_PAT
});

// On-prem: Basic authentication
const onpremBasicAuth = z.object({
  mode: z.literal('basic'),
  username: z.string(),
  password: redactedStringSchema, // injected from CONFLUENCE_PASSWORD
});
```

**Processing Schema** (Confluence-specific):

```typescript
const ProcessingConfigSchema = z.object({
  stepTimeoutSeconds: coercedPositiveIntSchema.prefault(300),
  concurrency: coercedPositiveIntSchema.prefault(5),
  scanIntervalCron: z.string().default('*/15 * * * *'),
  maxPagesToScan: z.coerce.number().int().positive().optional(),
});
```

**Config File Structure (YAML)**:

```yaml
confluence:
  instanceType: cloud  # or 'onprem'
  baseUrl: https://your-instance.atlassian.net/wiki
  auth:
    mode: api_token  # or 'pat' or 'basic'
    email: service-account@company.com
    # apiToken injected from CONFLUENCE_API_TOKEN env var
  apiRateLimitPerMinute: 100
  ingestSingleLabel: ai-ingest
  ingestAllLabel: ai-ingest-all

unique:
  serviceAuthMode: external  # or 'cluster_local'
  ingestionServiceBaseUrl: https://ingestion.unique.app
  scopeManagementServiceBaseUrl: https://scope.unique.app
  # For external: zitadelClientSecret injected from ZITADEL_CLIENT_SECRET

processing:
  stepTimeoutSeconds: 300
  concurrency: 5
  scanIntervalCron: "*/15 * * * *"
  maxPagesToScan: 100  # optional, for testing
```

### Error Handling

The loader fails fast on startup with descriptive errors for:
- `TENANT_CONFIG_PATH_PATTERN` not set
- No config files match the pattern
- Multiple config files found (single tenant only)
- YAML parsing failures
- Zod schema validation failures
- Missing required secrets for the selected auth mode

### Testing Strategy

- Unit tests for `tenant-config-loader.ts`
- Test scenarios:
  - Valid cloud config loads successfully
  - Valid onprem PAT config loads successfully
  - Valid onprem basic config loads successfully
  - Missing env var throws descriptive error
  - Invalid YAML throws error
  - Schema validation failure throws error
- Mock file system and environment variables
- Use existing `test/setup.ts` infrastructure

## Out of Scope

- Confluence API client implementation (separate ticket)
- Sync/scheduler logic (separate ticket)
- OAuth flow for Confluence Cloud (api_token sufficient for now)
- Multi-tenant support (single config file only)
- Config hot-reloading

## Tasks

1. **Create `processing.schema.ts`** - Define Confluence-specific processing configuration with stepTimeoutSeconds, concurrency, scanIntervalCron, and optional maxPagesToScan. Add defaults constants.

2. **Update `confluence.schema.ts` with full auth schema** - Replace placeholder auth with discriminated union supporting cloud api_token, onprem PAT, and onprem basic auth modes. Use redactedStringSchema for secrets.

3. **Create `tenant-config-loader.ts`** - Implement YAML config loading with glob pattern, secret injection from environment variables (CONFLUENCE_API_TOKEN, CONFLUENCE_PAT, CONFLUENCE_PASSWORD, ZITADEL_CLIENT_SECRET), and Zod validation. Export registerAs configs.

4. **Update `index.ts` exports** - Re-export tenant configs (confluenceConfig, uniqueConfig, processingConfig) and types from tenant-config-loader.

5. **Wire configs in `AppModule`** - Add confluenceConfig, uniqueConfig, processingConfig to ConfigModule.forRoot load array.

6. **Update `.env.example`** - Document TENANT_CONFIG_PATH_PATTERN and all secret environment variables with descriptions.

7. **Update README** - Add line pointing to .env.example for environment variable documentation.

8. **Write unit tests for tenant-config-loader** - Test valid config loading for all auth modes, secret injection, and error cases (missing files, invalid YAML, validation failures).
