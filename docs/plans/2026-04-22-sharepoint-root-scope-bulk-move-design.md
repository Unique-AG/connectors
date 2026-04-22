# Design: sharepoint-connector root scope migration via bulkMove

## Problem

When a site's configured `rootScopeId` changes between sync runs, `RootScopeMigrationService.migrateIfNeeded` moves every child scope from the old root to the new root by calling `UniqueScopesService.updateScopeParent` in a sequential `for` loop, then deletes the empty old root. For sites with many top-level children this is N network round-trips, N partial-failure windows, and N opportunities for divergent state if the connector crashes mid-loop.

`node-ingestion` already exposes a `bulkMove` GraphQL mutation (`services/node-ingestion/src/scope-operation/scope-operation-job.resolver.ts`) that moves many scopes in a single call. The sharepoint-connector does not use it.

Two blockers prevent the connector from calling `bulkMove` today:

1. The resolver is decorated with `@AllowAccess(AccessType.USER)` only. The sharepoint-connector and confluence-connector service accounts are not allowed.
2. The connector has no client wrapper, GraphQL document, or types for `bulkMove`.

## Solution

### Overview

Two-repo change, each on its own branch:

**Repo A — `unique/monorepo` (node-ingestion):** Widen the `bulkMove` resolver's `@AllowAccess(...)` to include `Integration.SHAREPOINT_CONNECTOR` and `Integration.CONFLUENCE_CONNECTOR`, matching the pattern already in place on `updateScope`, `deleteScope`, `paginatedScope`, and `generateScopesBasedOnPaths` in `services/node-ingestion/src/scope/scope.resolver.ts`.

**Repo B — `unique/connectors` (sharepoint-connector):** Add a `bulkMove` GraphQL mutation + service wrapper, and replace the per-child loop in `RootScopeMigrationService.migrateIfNeeded` with a single `bulkMoveScopes(childIds, newRootId)` call. Keep every other step identical: detection, same-id guard, non-recursive delete of the old root, and the existing `MigrationResult` contract.

The refactor is strictly 1-for-1 with today's outcome for recursive-mode sites: N calls become 1 call. Flat-mode migration remains broken (old root retains its direct content items and non-recursive delete fails). This is a pre-existing gap and is tracked as an out-of-scope follow-up, with a TODO in the code.

### Architecture

```
initializeRootScope(configuredRootScopeId, siteId, ingestionMode)
  └─> RootScopeMigrationService.migrateIfNeeded(newRootScopeId, siteId)
        1. Look up old root by externalId (legacy `spc:site:{siteId}` then new `spc:{siteId}/site`)   [unchanged]
        2. If not found or old.id == newRootScopeId -> no_migration_needed                            [unchanged]
        3. children = listChildrenScopes(oldRoot.id)                                                  [unchanged]
        4. If children.length > 0: bulkMoveScopes(children.map(c => c.id), newRootScopeId)            [NEW — replaces the loop]
        5. deleteScope(oldRoot.id)  // recursive: false                                               [unchanged]
        6. Return migration_completed                                                                 [unchanged]
```

#### Components changed

**Repo A — monorepo (node-ingestion)**

- `next/services/node-ingestion/src/scope-operation/scope-operation-job.resolver.ts`
  - Change `@AllowAccess(AccessType.USER)` on `bulkMove` to
    `@AllowAccess(AccessType.USER, Integration.SHAREPOINT_CONNECTOR, Integration.CONFLUENCE_CONNECTOR)`.
  - Remove the `// todo give access to SPC, Conf-Con, OutlookMCP` comment (Outlook MCP is out of scope per user direction; add it only if a separate ask comes in).
  - Add `Integration` import if missing.

**Repo B — connectors (sharepoint-connector)**

- `src/unique-api/unique-scopes/unique-scopes.consts.ts`
  - Add `BULK_MOVE_MUTATION` (gql document).
  - Add input/result types: `BulkMoveMutationInput` (`{ input: { scopeIds: string[]; targetScopeId: string } }`) and `BulkMoveMutationResult` (mirroring `MoveScopeResult` from node-ingestion — `{ bulkMove: { scopeIds: string[]; asyncMetadataRebuild: boolean; jobId?: string; affectedFiles?: number; message?: string } }`).
- `src/unique-api/unique-scopes/unique-scopes.service.ts`
  - Add `public async bulkMoveScopes(scopeIds: string[], targetScopeId: string): Promise<BulkMoveResult>`. Debug-log inputs (count + target), execute the mutation via `UniqueGraphqlClient`, return the payload.
- `src/sharepoint-synchronization/root-scope-migration.service.ts`
  - Replace the `for (const child of children)` loop and per-child `failedCount` accounting with:
    ```
    if (children.length > 0) {
      await this.uniqueScopesService.bulkMoveScopes(children.map(c => c.id), newRootScopeId);
    }
    ```
  - Keep the outer `try/catch` — any thrown error maps to `migration_failed` with the sanitized error message (same contract as today).
  - Add a TODO block above the call explaining the flat-mode gap: in flat mode, the old root directly holds content items; before touching the old root the migration must either list those items and include them in `contentIds`, or switch the delete to `recursive: true` once content has been re-owned to the new root.

### Error Handling

- `bulkMoveScopes` throws on any GraphQL / network / server error. The existing `try/catch` in `migrateIfNeeded` captures it, logs via `sanitizeError`, and returns `{ status: 'migration_failed', error }`. This matches the current "any child move failure fails the whole migration" contract; the only behavioral difference is that we no longer continue iterating after the first failure (today's loop did, but still ended in `migration_failed` with `failedCount > 0`). No partial-state risk is introduced because `bulkMove` is the server's atomic unit.
- Old-root deletion is unchanged: `deleteScope` with `recursive: false`. If `failedFolders.length > 0` we return `migration_failed`, same as today.
- Fire-and-forget on `asyncMetadataRebuild` / `jobId`: the connector does not poll. If the server kicks off async metadata rebuild we treat the mutation as successful and continue. This matches today's behavior (no job tracking) and the user's explicit choice.

### Testing Strategy

Behavioral tests in `src/sharepoint-synchronization/root-scope-migration.service.spec.ts`:

- Keep and reuse existing detection tests: no old root, legacy fallback, same-id guard.
- Rewrite the "move all children and delete old root" test to assert exactly one `bulkMoveScopes([childIds], newRootId)` call instead of N `updateScopeParent` calls.
- Add an "empty children" test: old root found, `listChildrenScopes` returns `[]`, assert `bulkMoveScopes` is **not** called and `deleteScope` still runs.
- Replace the "child scope move failures" and "partial child move failures with retry" tests with a single "bulkMove throws" test returning `migration_failed`.
- Keep old-root deletion failure tests as-is.

No new integration test setup needed — existing mocks of `UniqueScopesService` cover the new method with minimal additions.

For the node-ingestion change, existing resolver tests (if any) should still pass; adding a connector access type does not change behavior for existing callers. Manual verification: a connector-signed request to `bulkMove` reaches the resolver in the local dev stack.

## Out of Scope

- **Flat-mode root migration.** The old root in flat mode holds content items directly. Today's migration is already broken for this case (non-recursive delete fails). Fixing it requires either a content-listing query on the connector side to populate `contentIds` in `bulkMove`, or switching the delete to `recursive: true` once content has been re-owned. Tracked as a follow-up ticket; a TODO will be added in `root-scope-migration.service.ts`.
- **Outlook semantic MCP access to `bulkMove`.** The original resolver comment hints at it; out of scope here unless separately requested.
- **Retries / idempotency re-architecture.** The existing migration is invoked each sync and re-checks state on re-entry; this refactor preserves that.
- **`asyncMetadataRebuild` job tracking or polling** on the connector side.
- **Content item migration tests**, since content items are not moved in this refactor.

## Tasks

### Repo A — unique/monorepo (new branch)

1. **Branch and locate resolver.** Create a new branch (e.g., `node-ingestion/feat/bulk-move-connector-access`) off the monorepo default branch. Open `next/services/node-ingestion/src/scope-operation/scope-operation-job.resolver.ts`.

2. **Widen `@AllowAccess` on `bulkMove`.** Change the decorator to include `Integration.SHAREPOINT_CONNECTOR` and `Integration.CONFLUENCE_CONNECTOR`. Add the `Integration` import if not already present. Remove the obsolete `// todo give access to SPC, Conf-Con, OutlookMCP` comment.

3. **Verify and commit.** Run project formatter + typecheck + existing tests for the scope-operation module. Commit with a conventional-commits message in node-ingestion's scope. Open PR in the monorepo.

### Repo B — unique/connectors (current branch `sharepoint-connector/fix/refactor-root-scope-migration-bulk-move`)

4. **Add `BULK_MOVE_MUTATION` document and types.** In `src/unique-api/unique-scopes/unique-scopes.consts.ts`, add the gql mutation document plus `BulkMoveMutationInput` and `BulkMoveMutationResult` types mirroring the server contract.

5. **Add `bulkMoveScopes` service method.** In `src/unique-api/unique-scopes/unique-scopes.service.ts`, implement `bulkMoveScopes(scopeIds, targetScopeId)` that invokes the new mutation via `UniqueGraphqlClient` and returns the payload. Log input counts at debug level.

6. **Replace per-child loop in `RootScopeMigrationService`.** In `src/sharepoint-synchronization/root-scope-migration.service.ts`, replace the `for` loop and `failedCount` accounting with a single `bulkMoveScopes` call, guarded by `children.length > 0`. Preserve the existing outer `try/catch` and `MigrationResult` contract. Add the flat-mode TODO.

7. **Update tests.** Rewrite affected sections of `root-scope-migration.service.spec.ts` to assert a single bulk call, add the empty-children case, and replace partial-failure tests with a single "bulkMove throws" case. Add minimal unit coverage for the new `bulkMoveScopes` service method if none is inherited from the spec.

8. **Verify and push.** Run `biome`, `tsc`, and `vitest` in the sharepoint-connector package. Confirm release-please scope conventions match the existing PR title. Push and open PR.
