# Design: Tenant Auth Factory Naming Contract

## Problem

The current `TenantAuthFactory` class in confluence-connector only creates **Confluence source auth** accessors (OAuth 2LO / PAT), but its generic name suggests it handles all tenant auth. Once Unique/Zitadel service auth is added (already modeled in `unique.schema.ts` with `cluster_local` and `external` modes), the generic name becomes ambiguous — making logs, errors, and DI wiring confusing.

The sharepoint-connector already has domain-specific names (`UniqueAuthService` for Zitadel, `MicrosoftAuthenticationService` for source-system auth), so confluence-connector should follow the same clarity.

## Solution

### Overview

Rename `TenantAuthFactory` to `ConfluenceTenantAuthFactory` to make the Confluence-source-auth domain explicit. Define a naming contract that reserves `UniqueTenantAuthFactory` for the future Unique/Zitadel tenant auth layer. Both factories are tenant-scoped: they take per-tenant config and produce per-tenant auth accessors.

This is a naming-only refactor with no runtime behavior change. The rename touches the class, its file, barrel exports, DI wiring in `TenantModule`, consumer code in `TenantRegistry`, and all related test files.

### Architecture

Two auth domains map to two factories, each driven by the corresponding config section:

```
TenantConfig
├── confluence: ConfluenceConfig  →  ConfluenceTenantAuthFactory.create(config.confluence)
│     └── auth: oauth_2lo | pat
│     └── returns: TenantAuth { getAccessToken() }
│
└── unique: UniqueConfig          →  UniqueTenantAuthFactory.create(config.unique)  [future]
      └── serviceAuthMode: cluster_local | external (Zitadel)
      └── returns: TenantAuth { getAccessToken() }
```

Call sites in `TenantRegistry.onModuleInit()`:

```typescript
// Today (this task)
this.tenants.set(name, {
  ...
  auth: this.confluenceAuthFactory.create(config.confluence),
});

// Future (out of scope)
this.tenants.set(name, {
  ...
  confluenceAuth: this.confluenceAuthFactory.create(config.confluence),
  uniqueAuth: this.uniqueAuthFactory.create(config.unique),
});
```

The `TenantAuth` interface stays unchanged — both domains produce `{ getAccessToken(): Promise<string> }`. Domain-specific strategies (OAuth2Lo, PAT, Zitadel client-credentials, cluster-local passthrough) remain internal to each factory.

### Error Handling

- Factory names must appear in thrown/logged errors so domain is immediately clear (e.g. `ConfluenceTenantAuthFactory: Unsupported auth mode` vs `UniqueTenantAuthFactory: Zitadel token request failed`).
- Token cache behavior stays domain-local: failures in Confluence auth never affect Unique auth and vice versa.
- No change to existing error paths — only the class name in log output changes from `TenantAuthFactory` to `ConfluenceTenantAuthFactory`.

### Testing Strategy

- Rename-only: existing `tenant-auth.factory.spec.ts` tests keep their behavior assertions unchanged; only the class name in `describe()` and imports change.
- Verify `tenant-registry.spec.ts` still compiles and passes with updated import.
- Run `npm run check-all` to catch any missed references.
- No new test cases needed — this is a pure rename with no logic change.

## Out of Scope

- Implementing `UniqueTenantAuthFactory` runtime (future task when Unique ingestion pipeline is built).
- Renaming `TenantContext.auth` to `TenantContext.confluenceAuth` (follow-up when second auth domain is wired).
- Changing any auth strategy internals (OAuth2Lo, PAT, TokenCache).
- Modifying scheduler or sync pipeline behavior.

## Tasks

1. **Rename TenantAuthFactory to ConfluenceTenantAuthFactory** - Rename the class, update the filename from `tenant-auth.factory.ts` to `confluence-tenant-auth.factory.ts`, update barrel export in `index.ts`, and update all import paths across `tenant.module.ts`, `tenant-registry.ts`, and test files.

2. **Update TenantRegistry to use new name** - Change constructor injection and `this.authFactory` references to use `confluenceAuthFactory` as the property name for clarity.

3. **Run checks and verify no regressions** - Execute `npm run check-all` and `npx vitest run` to confirm the rename is complete with no missed references or test failures.
