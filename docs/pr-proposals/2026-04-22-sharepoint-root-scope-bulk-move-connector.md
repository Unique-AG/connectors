# PR Proposal — connectors repo (sharepoint-connector)

## Title
fix(sharepoint-connector): use bulkMove for root scope migration

## Description
- Replace the per-child `updateScopeParent` loop in `RootScopeMigrationService.migrateIfNeeded` with a single `bulkMove` GraphQL mutation.
- Add `BULK_MOVE_MUTATION` document, types, and a `UniqueScopesService.bulkMoveScopes(scopeIds, targetScopeId)` wrapper.
- Preserve the existing `MigrationResult` contract and non-recursive old-root deletion; only the number of network calls changes.
- Tests rewritten to assert a single bulk call, cover the empty-children short-circuit, and collapse partial-failure cases into a single "bulkMove throws" assertion.
- Adds a TODO flagging flat-mode migration as a known gap to be fixed in a follow-up (direct content items on the old root are not yet moved).

## Depends on
- node-ingestion PR widening `@AllowAccess` on `bulkMove` to include `SHAREPOINT_CONNECTOR` and `CONFLUENCE_CONNECTOR`. Must land first.
