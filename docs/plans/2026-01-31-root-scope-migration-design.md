# Design: Root Scope Migration for UNIQUE_SCOPE_ID Changes

## Problem

When the `UNIQUE_SCOPE_ID` (root scope ID) is changed in the SharePoint connector configuration, the connector starts syncing content to a new root scope. However, all existing content (child scopes and files) remains under the old root scope.

The file-diff mechanism doesn't detect this because the actual SharePoint file URLs haven't changed - only the Unique scope hierarchy has changed. This results in orphaned content under the old root while new content syncs to the new root.

We need a way to detect when the root scope has changed and migrate existing child scopes to the new root.

## Solution

### Overview

Create a new `RootScopeMigrationService` that detects and handles root scope changes during initialization. The service uses the `externalId` field (`spc:site:<site-id>`) as the source of truth to identify which scope "owns" a SharePoint site's content.

When `initializeRootScope` encounters a new root scope without an `externalId`, it calls the migration service to check if an old root scope exists for the same site. If found, the service migrates all child scopes to the new root, deletes the empty old root, and allows the normal flow to set the `externalId` on the new root.

The migration is idempotent and resumable - if interrupted, the next sync cycle will detect the incomplete state and continue from where it left off.

### Architecture

#### New Service: `RootScopeMigrationService`

Location: `src/sharepoint-synchronization/root-scope-migration.service.ts`

Responsibilities:
- Detect if a previous root scope exists for a site (via `externalId` lookup)
- Migrate child scopes from old root to new root
- Delete the old root scope after migration
- Handle resumption of partial migrations

Key method:
```typescript
async migrateIfNeeded(newRootScopeId: string, siteId: string): Promise<MigrationResult>
```

Returns one of:
- `{ status: 'no_migration_needed' }` - No old root found, proceed normally
- `{ status: 'migration_completed' }` - Successfully migrated all children
- `{ status: 'migration_failed', error }` - Failed, will retry next sync

#### Changes to `UniqueScopesService`

Add two new methods:

1. Query scope by `externalId`:
```typescript
async getScopeByExternalId(externalId: string): Promise<Scope | null>
```

2. Update scope parent:
```typescript
async updateScopeParent(scopeId: string, newParentId: string): Promise<void>
```

Extend `PaginatedScopeQueryInput` to support `externalId` filter.

#### Changes to `ScopeManagementService`

In `initializeRootScope`, after fetching the root scope and before setting `externalId`:

```typescript
if (!rootScope.externalId) {
  const migrationResult = await this.rootScopeMigrationService.migrateIfNeeded(
    rootScopeId,
    siteId,
  );
  if (migrationResult.status === 'migration_failed') {
    throw new Error(`Root scope migration failed: ${migrationResult.error}`);
  }
  // Then proceed to set externalId as before
}
```

### Migration Flow

1. `initializeRootScope` fetches the new root scope
2. If `externalId` is null, call `migrateIfNeeded(newRootScopeId, siteId)`
3. Migration service queries for scope with `externalId` = `spc:site:<siteId>`
4. If no old root found → return `no_migration_needed`
5. If old root found:
   a. Fetch all child scopes of old root via `listChildrenScopes`
   b. For each child, update parent to new root via `updateScopeParent`
   c. Delete empty old root via `deleteScopeRecursively`
   d. Return `migration_completed`
6. `initializeRootScope` sets `externalId` on new root (normal flow)

### Error Handling

Migration Failure Behavior:
- When `migrateIfNeeded` returns `migration_failed`, `initializeRootScope` throws
- `syncSite` catches the error and returns `{ status: 'failure', step: SyncStep.RootScopeInit }`
- Site is skipped for this sync cycle; other sites continue normally

Resumable Migration States:

| State | Detection | Action |
|-------|-----------|--------|
| No migration needed | No scope with `spc:site:<siteId>` exists | Proceed normally |
| Migration not started | Old root has `externalId`, new root has none | Start migration |
| Migration in progress | Both roots exist, some children moved | Continue moving remaining children |
| Migration almost done | Old root exists but has no children | Delete old root |
| Migration complete | New root has `externalId`, no old root | Proceed normally |

The migration is idempotent: safe to retry on each sync until complete.

### Testing Strategy

Unit tests for `RootScopeMigrationService`:

Migration detection:
- No old root exists → returns `no_migration_needed`
- Old root exists with children → triggers migration
- Old root exists but empty (partial migration) → deletes old root only

Migration execution:
- Successfully moves all child scopes to new root
- Successfully deletes empty old root
- Handles API errors during child scope move (returns `migration_failed`)
- Handles API errors during old root deletion (returns `migration_failed`)

Integration:
- `ScopeManagementService` tests verify `migrateIfNeeded` is called when `externalId` is null
- Verify sync fails gracefully when migration fails

## Out of Scope

- File-level migration: Files don't exist at root level, only child scopes need moving
- Multi-site parallel migration: Each site migrates independently during its sync
- Rollback mechanism: Failed migrations retry next sync rather than rolling back
- UI notifications: No user-facing alerts for migration (logs only)
- Migration-specific metrics: Existing sync metrics suffice

## Tasks

1. **Extend `UniqueScopesService` with `externalId` query** - Add `getScopeByExternalId` method and extend `PaginatedScopeQueryInput` to support `externalId` filter in the GraphQL query.

2. **Add `updateScopeParent` to `UniqueScopesService`** - Add method to update a scope's parent using the `parrentScope: { connect: { id } }` mutation input.

3. **Create `RootScopeMigrationService`** - Implement the migration service with `migrateIfNeeded` method that detects old root, moves children, and deletes old root. Include proper logging and error handling.

4. **Integrate migration into `ScopeManagementService`** - Call `migrateIfNeeded` in `initializeRootScope` when `externalId` is null. Throw on migration failure to skip site processing.

5. **Add unit tests for `RootScopeMigrationService`** - Cover all migration states (no migration needed, full migration, partial migration resume, failure cases).
