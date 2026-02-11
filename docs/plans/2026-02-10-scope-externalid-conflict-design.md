# Design: Fix scope externalId conflict on folder moves

**Ticket:** UN-17025

## Problem

When a SharePoint folder moves within the same drive, the connector creates a new scope at the new path but cannot assign the `externalId` because the old orphan scope at the previous path still holds it. SharePoint preserves the folder's `item.id` across moves, so the connector computes the same `externalId` (e.g. `spc:folder:{siteId}/{folderId}`) for both the old and new scope. The Unique API enforces a unique constraint on `externalId`, causing the update to fail.

The error is caught and logged as a warning, leaving the new scope without an `externalId`. The old orphan scope is never cleaned up because scope deletion only happens when an entire site is explicitly marked as `deleted` in configuration.

**Reproduction:** Move any folder to a different location within the same SharePoint drive, then run a sync.

## Solution

### Overview

Two-phase fix: **mark-then-sweep**.

During scope creation, when a new scope needs an `externalId` that's already held by a different (old) scope, rename the old scope's `externalId` to a `spc:pending-delete:` prefix. This frees the `externalId` for the new scope and marks the old one for cleanup.

After content sync completes (file moves have already relocated files from old scopes to new ones), sweep all scopes marked with the `spc:pending-delete:` prefix and delete them non-recursively, children-first.

### Architecture

#### Initial sync detection

In `initializeRootScope`, the root scope's `externalId` is already checked. If it was `null` before being set, this is a first-time sync. Return an `isInitialSync` flag as part of `RootScopeInfo` and propagate it through `SharepointSyncContext`. When `isInitialSync` is true, skip the conflict check entirely -- there are no old scopes to conflict with.

#### Phase 1: Mark conflicting scopes (during `batchCreateScopes`)

In `ScopeManagementService.updateNewlyCreatedScopesWithExternalId`, before calling `updateScopeExternalId` on a new scope (skipped when `isInitialSync` is true):

1. Call `getScopeByExternalId(desiredExternalId)` to check if another scope already holds it.
2. If a different scope holds it, rename its `externalId` from `spc:<type>:{siteId}/{id}` to `spc:pending-delete:<type>:{siteId}/{id}`.
3. Set the `externalId` on the new scope as normal.

#### Phase 2: Sweep orphaned scopes (after content sync, per site)

A new step in `SharepointSynchronizationService.syncSite`, placed after `contentSyncService.syncContentForSite` and scoped to the current site:

1. Query `paginatedScope` with `externalId: { startsWith: "spc:pending-delete:{siteId}/" }` to find marked orphans **only for this site**.
2. Sort children-first (deepest scopes first by path depth) so non-recursive deletion succeeds.
3. Delete each scope non-recursively via the existing `deleteScope` method.
4. Log results. Failures are warnings, not fatal to the sync.

This runs per-site rather than globally, ensuring each site's orphans are cleaned up immediately after its own content sync completes and preventing cross-site interference.

#### Updated `syncSite` flow

```
1. initializeSiteContext
2. getAllSiteItems
3. batchCreateScopes             <- marks conflicting old scopes with pending-delete prefix
4. syncContentForSite            <- moves files from old scopes to new ones
5. syncPermissionsForSite
6. deleteOrphanedScopes  [NEW]   <- sweeps scopes with pending-delete prefix, children-first
```

#### Files changed

| File | Change |
|------|--------|
| `unique-scopes.consts.ts` | Extend `PaginatedScopeQueryInput.where.externalId` to accept `startsWith` alongside `equals` |
| `unique-scopes.service.ts` | Add `listScopesByExternalIdPrefix(prefix)` method that paginates through all matching scopes |
| `logging.util.ts` | Add `PENDING_DELETE_PREFIX` constant (`spc:pending-delete:`) |
| `scope-management.service.ts` | Return `isInitialSync` from `initializeRootScope`. Update `updateNewlyCreatedScopesWithExternalId` to skip conflict check on initial sync, lookup-and-mark otherwise. Add `deleteOrphanedScopes(siteId)` public method |
| `sharepoint-sync-context.interface.ts` | Add `isInitialSync` field to `SharepointSyncContext` |
| `sharepoint-synchronization.service.ts` | Call `scopeManagementService.deleteOrphanedScopes(siteId)` in `syncSite` after content sync for each site. Add `SyncStep.OrphanScopeCleanup` enum value |

### Error Handling

- **Marking fails:** Log warning, still attempt `updateScopeExternalId` on the new scope. Worst case is the status quo (the warning we already get today).
- **Sweep query fails:** Log warning, skip cleanup. Orphans survive until the next sync cycle retries.
- **Individual scope deletion fails:** Log warning per scope, continue with the rest. A scope might not be empty if content sync had a partial failure; it will be retried next cycle.
- **No errors halt the sync.** The sweep is best-effort cleanup.

### Testing Strategy

Using existing `@suites/unit` + `TestBed` patterns from `scope-management.service.spec.ts`:

1. **Mark-and-set happy path:** Old scope found by externalId, renamed to `pending-delete` prefix, new scope gets the externalId.
2. **No conflict:** `getScopeByExternalId` returns null, proceeds normally (existing behavior preserved).
3. **Mark fails:** Old scope rename fails, `updateScopeExternalId` still attempted, warning logged.
4. **Sweep happy path:** Two orphan scopes found (parent + child), deleted children-first.
5. **Sweep with non-empty scope:** Deletion fails for one scope, logged as warning, others still deleted.

## Out of Scope

- **Full garbage collection of all orphan scopes.** This fix only handles the move scenario via mark-then-sweep. A broader orphan detection pass (comparing entire scope tree against SharePoint) is a separate effort.
- **Scope reparenting.** We considered moving old scopes to match the new hierarchy but rejected it due to complexity with nested moves and structural changes within moved folders.
- **Handling folder renames without moves.** If a folder is renamed in place (same parent, new name), `generateScopesBasedOnPaths` creates a new scope with the new name. The same mark-then-sweep mechanism handles this case identically.

## Tasks

1. **Extend `PaginatedScopeQueryInput` for `startsWith` filter** - Add `startsWith` option to the `externalId` field in the query input type and add `listScopesByExternalIdPrefix` to `UniqueScopesService`.

2. **Add `PENDING_DELETE_PREFIX` constant** - Add the `spc:pending-delete:` prefix constant to `logging.util.ts` alongside the existing `EXTERNAL_ID_PREFIX`.

3. **Add `isInitialSync` flag** - Return `isInitialSync` (root scope had no externalId) from `initializeRootScope` in `RootScopeInfo`, add it to `SharepointSyncContext`, and pass it through to `batchCreateScopes`.

4. **Update `updateNewlyCreatedScopesWithExternalId` to mark conflicts** - When `isInitialSync` is false: before setting externalId, look up the existing holder via `getScopeByExternalId`. If found on a different scope, rename its externalId to the pending-delete prefix. Then set the externalId on the new scope. When `isInitialSync` is true: skip the lookup entirely.

5. **Add `deleteOrphanedScopes` to `ScopeManagementService`** - Accept a siteId, query scopes by `spc:pending-delete:{siteId}/` prefix, sort children-first, delete each non-recursively. Log results.

6. **Wire orphan cleanup into `syncSite`** - Call `deleteOrphanedScopes(siteId)` after content sync for each site in `SharepointSynchronizationService.syncSite`. Add `SyncStep.OrphanScopeCleanup` enum value.

7. **Add tests** - Cover the mark-and-set flow (happy path, no conflict, mark failure, initial sync skip) and the sweep flow (happy path, partial failure) in `scope-management.service.spec.ts`.
