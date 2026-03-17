# Design: Deleted Tenant Content Cleanup

## Problem

When a Confluence connector tenant's status is set to `deleted` in its YAML config, the connector currently skips the tenant entirely — identical to `inactive` status. There is a TODO at `src/config/tenant-config-loader.ts:108` to implement actual cleanup of previously ingested content. Without this, deleted tenant content remains in Unique indefinitely, consuming storage and appearing in search results.

The SharePoint connector already implements this pattern: during each sync cycle, it categorizes sites as active/inactive/deleted, processes deletions first (files then scopes), then syncs active sites. We need the Confluence connector equivalent.

## Solution

### Overview

Extend the tenant config loader to also parse and return deleted tenant configs. In `TenantRegistry`, keep a separate `deletedTenants` map and register only the `UniqueApiClient` for each deleted tenant (via the same factory and service registry used for active tenants). Add a `processDeletedTenants()` method that deletes files and child scopes while preserving the root scope. The `TenantSyncScheduler` calls this cleanup before scheduling active tenant syncs.

An empty root scope (no child scopes, no files) signals that cleanup was already performed, avoiding redundant work on subsequent startups.

### `tenant-config-loader.ts`

Parse `TenantConfigSchema` for deleted tenants (currently skipped at line 107). Add a new `getDeletedTenantConfigs()` export. The existing `getTenantConfigs()` continues to return only active tenants.

```typescript
const activeConfigs: NamedTenantConfig[] = [];
const deletedConfigs: NamedTenantConfig[] = [];

for (const entry of entries) {
  const fileContent = readFileSync(entry.path, 'utf-8');
  const rawConfig = load(fileContent);
  const { status } = TenantStatusSchema.parse(rawConfig);
  const config = TenantConfigSchema.parse(rawConfig);

  if (status === TenantStatus.Deleted) {
    deletedConfigs.push({ name: entry.name, config });
    continue;
  }

  if (status === TenantStatus.Inactive) {
    continue;
  }

  activeConfigs.push({ name: entry.name, config });
}

// new export
let cachedDeletedConfigs: NamedTenantConfig[] | null = null;
export function getDeletedTenantConfigs(): NamedTenantConfig[] {
  if (cachedDeletedConfigs) {
    return cachedDeletedConfigs;
  }
  getTenantConfigs(); // triggers loadTenantConfigs() which populates both caches
  return cachedDeletedConfigs ?? [];
}
```

### `TenantRegistry`

Separate `deletedTenants` map. Register only `UniqueApiClient` for deleted tenants. Cleanup method retrieves the client from the service registry.

```typescript
export class TenantRegistry implements OnModuleInit {
  private readonly tenants = new Map<string, TenantContext>();
  private readonly deletedTenants = new Map<string, TenantContext>();

  public onModuleInit(): void {
    // existing active tenant registration (unchanged)
    const tenantConfigs = getTenantConfigs();
    for (const { name: tenantName, config } of tenantConfigs) {
      // ... same as today: full service registration ...
    }

    // register deleted tenants with only UniqueApiClient
    const deletedConfigs = getDeletedTenantConfigs();
    for (const { name: tenantName, config } of deletedConfigs) {
      const tenant: TenantContext = { name: tenantName, config, isScanning: false };
      this.deletedTenants.set(tenantName, tenant);

      tenantStorage.run(tenant, () => {
        const uniqueClient = this.uniqueApiFactory.create({
          auth: this.buildUniqueAuthConfig(config.unique),
          ingestion: {
            baseUrl: config.unique.ingestionServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          scopeManagement: {
            baseUrl: config.unique.scopeManagementServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          metadata: { clientName: 'confluence-connector', tenantKey: tenantName },
        });
        this.serviceRegistry.register(tenantName, UniqueApiClient, uniqueClient);
        this.logger.log({ tenantName, msg: 'Deleted tenant registered for cleanup' });
      });
    }
  }

  public async processDeletedTenants(): Promise<void> {
    for (const tenant of this.deletedTenants.values()) {
      try {
        await this.run(tenant, async () => {
          const uniqueClient = this.serviceRegistry.getService(UniqueApiClient);
          await this.cleanupTenant(tenant, uniqueClient);
        });
      } catch (error) {
        this.logger.error({ tenantName: tenant.name, err: error, msg: 'Tenant cleanup failed' });
      }
    }
  }

  private async cleanupTenant(tenant: TenantContext, uniqueClient: UniqueApiClient): Promise<void> {
    const { scopeId, useV1KeyFormat } = tenant.config.ingestion;

    // 1. Check root scope exists
    const rootScope = await uniqueClient.scopes.getById(scopeId);
    if (!rootScope) {
      this.logger.log({ tenantName: tenant.name, msg: `Root scope ${scopeId} not found, skipping` });
      return;
    }

    // 2. Check if already cleaned up
    const childScopes = await uniqueClient.scopes.listChildren(scopeId);
    const fileCount = useV1KeyFormat
      ? childScopes.length // if no children, no files either (V1 can't check by prefix)
      : await uniqueClient.files.getCountByKeyPrefix(tenant.name);

    if (childScopes.length === 0 && fileCount === 0) {
      this.logger.log({ tenantName: tenant.name, msg: 'Already cleaned up, skipping' });
      return;
    }

    // 3. Delete files
    if (useV1KeyFormat) {
      // V1 keys have no tenant prefix — delete files by querying each scope's ownerId
      await this.deleteFilesByScopes(childScopes, uniqueClient);
    } else {
      // V2 keys: {tenantName}/{spaceId}_{spaceKey}/{id} — delete by prefix
      const deletedCount = await uniqueClient.files.deleteByKeyPrefix(tenant.name);
      this.logger.log({ tenantName: tenant.name, deletedCount, msg: 'Files deleted by key prefix' });
    }

    // 4. Delete child scopes (not root!)
    for (const child of childScopes) {
      const result = await uniqueClient.scopes.delete(child.id, { recursive: true });
      this.logger.log({
        tenantName: tenant.name,
        scopeName: child.name,
        succeeded: result.successFolders.length,
        failed: result.failedFolders.length,
        msg: 'Child scope deleted',
      });
    }

    this.logger.log({ tenantName: tenant.name, msg: 'Tenant cleanup completed' });
  }

  private async deleteFilesByScopes(
    scopes: Scope[],
    uniqueClient: UniqueApiClient,
  ): Promise<void> {
    // IMPORTANT LIMITATION: This approach only works because the Confluence connector
    // uses a flat scope hierarchy — root scope → one child scope per space, with NO
    // sub-scopes beneath them. Files are owned directly by these child scopes via
    // ownerId. If the scope hierarchy ever becomes nested (sub-scopes within space
    // scopes), this method would miss files owned by deeper scopes and would need to
    // be updated to walk the full scope tree recursively.
    for (const scope of scopes) {
      const fileIds = await uniqueClient.files.getFileIdsByScope(scope.id);
      if (fileIds.length > 0) {
        await uniqueClient.files.deleteByIds(fileIds);
        this.logger.log({
          scopeName: scope.name,
          deletedCount: fileIds.length,
          msg: 'Files deleted by scope ownership',
        });
      }
    }
  }
}
```

### `TenantSyncScheduler`

Call `processDeletedTenants()` before scheduling active tenant syncs.

```typescript
public onModuleInit(): void {
  // process deletions first, then schedule active syncs
  void this.tenantRegistry.processDeletedTenants().then(() => {
    if (this.tenantRegistry.tenantCount === 0) {
      this.logger.warn({ msg: 'No tenants registered — no sync jobs will be scheduled' });
      return;
    }

    for (const tenant of this.tenantRegistry.getAllTenants()) {
      this.logger.log({ tenantName: tenant.name, msg: 'Triggering initial sync' });
      void this.syncTenant(tenant);
      this.registerCronJob(tenant);
    }
  });
}
```

### File deletion strategy

- **V2 tenants** (default): Use `files.deleteByKeyPrefix(tenantName)`. Keys are `{tenantName}/{spaceId}_{spaceKey}/{id}`, so one prefix query covers all files.
- **V1 tenants** (legacy): Keys are `{spaceId}_{spaceKey}/{id}` with no tenant prefix. Instead, query files by `ownerId` (the scopeId they were ingested into) for each child scope, then delete by IDs. This requires adding a `getFileIdsByScope(scopeId)` method to the files service that queries with `where: { ownerId: { equals: scopeId }, ownerType: { equals: 'SCOPE' } }` — the GraphQL `ContentWhereInput` already supports this (used by `getIdsByScopeAndMetadataKey`). **Important limitation**: this only works because the Confluence connector uses a flat scope hierarchy (root → one child per space, no sub-scopes). Files are owned directly by the child scopes. If nested sub-scopes are ever introduced, the deletion would need to walk the full scope tree recursively.

### V1 key format edge case

If a deleted tenant used `useV1KeyFormat: enabled`, content keys are `{spaceId}_{spaceKey}/{pageId}` with no tenant name prefix. We cannot safely identify files by a tenant-level key prefix. For V1 tenants:
- Query files by `ownerId` for each child scope and delete by IDs.
- **Limitation**: This relies on the flat scope hierarchy (root → space scopes, no deeper nesting). All files are owned directly by the child scopes. If nested sub-scopes are ever introduced, the scope-based deletion would miss files in deeper scopes and would need recursive scope traversal.
- The "is empty" check uses `listChildren` — if no child scopes remain, cleanup is done.

### Error Handling

- **Per-tenant isolation**: Each deleted tenant is processed in its own try/catch. Errors are logged and processing continues with the next tenant.
- **Root scope not found**: Treated as "nothing to clean up" (may have been manually deleted). Logged at info level.
- **Already empty**: Detected via child scope count + file count checks. Logged at info level, no work performed.
- **Partial failure**: If file deletion succeeds but scope deletion fails (or vice versa), the next startup will detect remaining content and retry.

### Testing Strategy

- **`tenant-config-loader.spec.ts`**: Add tests for the new `getDeletedTenantConfigs()` function — verify it returns parsed configs for deleted tenants only.
- **`TenantRegistry`**: Add tests for `processDeletedTenants()` covering: happy path (files + scopes deleted), already cleaned up (empty root scope), root scope not found, error in one tenant doesn't block others, V1 key format uses scope-based file deletion, V2 uses key prefix deletion.

## Out of Scope

- Automatic removal of the tenant config YAML file after cleanup.
- Notification/webhook when cleanup completes.
- Cleanup scheduling on a cron (runs once at startup; re-runs on next restart if incomplete).
- Deleting the root scope itself (preserved for admin management).

## Tasks

1. **Export deleted tenant configs from `tenant-config-loader.ts`** - Parse `TenantConfigSchema` for deleted tenants and expose them via `getDeletedTenantConfigs()`. Remove the existing TODO. Add tests.

2. **Add `getFileIdsByScope()` to files service** - Add a method to query file IDs by `ownerId` (scope ID) without metadata filtering. Uses the existing `ContentWhereInput` GraphQL type with `ownerId: { equals: scopeId }`. Needed for V1 key format file deletion.

3. **Add `processDeletedTenants()` to `TenantRegistry`** - Add `deletedTenants` map. Register deleted tenants with only `UniqueApiClient` in `onModuleInit()`. Implement `cleanupTenant()` with the two-strategy file deletion (key prefix for V2, scope-based for V1), child scope deletion, and empty-check skip logic. Add tests.

4. **Integrate into `TenantSyncScheduler`** - Call `tenantRegistry.processDeletedTenants()` in `onModuleInit()` before scheduling active tenant syncs.
