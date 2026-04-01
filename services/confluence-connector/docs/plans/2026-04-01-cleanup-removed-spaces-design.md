# Design: Cleanup Removed Confluence Spaces

**Ticket:** UN-18296

## Problem

When a Confluence space is removed (deleted, or all `ai-ingest`/`ai-ingest-all` labels removed from its pages), the files ingested from that space are not deleted from Unique. They remain orphaned indefinitely.

Root cause: `FileDiffService.computeDiff()` groups discovered pages/attachments by spaceKey and only calls `performFileDiff()` for spaces that appear in the current discovery results. When a space has zero discovered pages, it is absent from the grouping, so `performFileDiff()` is never invoked for that space's partialKey. Additionally, the existing safety check (`validateNoAccidentalFullDeletion`) would block correct behavior even if the space were included.

Space scopes in Unique are also never cleaned up.

## Solution

### Overview

Detect removed spaces by comparing existing scope children against discovered spaceKeys. For each orphaned space, delete its files via `files.deleteByKeyPrefix(partialKey)`, then delete the scope via `scopes.delete(scopeId)`.

To reconstruct the partialKey for a removed space (which requires the Confluence numeric spaceId), enrich the scope's externalId to include spaceId alongside spaceKey.

### Architecture

**1. Enrich scope externalId with spaceId**

In `ScopeManagementService.ensureSpaceScopes()`, change the externalId format:
- Old: `confc:{tenantName}:{spaceKey}`
- New: `confc:{tenantName}:{spaceId}:{spaceKey}`

The `ensureSpaceScopes` method receives spaceKeys but also needs spaceIds now. The caller (`synchronize()`) must pass a mapping of spaceKey to spaceId derived from discovery results.

Always update the externalId (not just when it's missing) to migrate existing scopes to the new format.

**2. Detect removed spaces in `synchronize()`**

After discovery and diff, before ingestion:
1. Call `scopes.listChildren(rootScopeId)` to get all existing space scopes.
2. Parse each child scope's externalId to extract spaceKey and spaceId.
3. Build the set of discovered spaceKeys from `discoveredPages` and `discoveredAttachments`.
4. Orphaned scopes = children whose spaceKey is NOT in the discovered set.

**3. Clean up orphaned spaces**

For each orphaned scope:
1. Parse spaceId from the scope's externalId.
2. Reconstruct partialKey: `{spaceId}_{spaceKey}` (V1) or `{tenantName}/{spaceId}_{spaceKey}` (V2).
3. Call `files.deleteByKeyPrefix(partialKey)` to remove all files.
4. Call `scopes.delete(scopeId)` to remove the scope.

Files are deleted before the scope to avoid orphaning files if scope deletion succeeds but file deletion doesn't.

**4. Where cleanup lives**

Following the SharePoint connector's pattern, space cleanup logic lives in `ConfluenceSynchronizationService.synchronize()` as a new step after the existing diff/ingestion/deletion flow. A new method on `ScopeManagementService` (e.g., `cleanupRemovedSpaces()`) handles the detection and deletion, called from `synchronize()`.

### Error Handling

- Each orphaned space cleanup is wrapped in try/catch. One failure does not block others.
- If `files.deleteByKeyPrefix` fails: log error, skip scope deletion. Scope persists, retry next cycle.
- If `scopes.delete` fails after files were deleted: log error, continue. Empty scope retried next cycle.
- If externalId is missing or unparseable (no spaceId): log error, skip that scope. It gets migrated on next sync while the space still exists.

### Testing Strategy

Use the existing test setup from `file-diff.service.spec.ts` as reference. Behavioral tests for:

1. **ExternalId parsing**: parse new format `confc:{tenant}:{spaceId}:{spaceKey}` correctly. Handle old format (3 segments) and missing externalId gracefully.
2. **Orphan detection**: given scope children and discovered spaceKeys, correctly identify removed spaces.
3. **Cleanup flow**: mock `scopes.listChildren`, `files.deleteByKeyPrefix`, `scopes.delete`. Verify files are deleted before scope, errors are caught per-space, and cleanup is skipped for unparseable externalIds.
4. **ExternalId migration**: verify that `ensureSpaceScopes` updates old-format externalIds to include spaceId.
5. **Edge cases**: no orphaned spaces (no-op), all spaces removed, scope with no externalId.

## Out of Scope

- Cleaning up scopes that were created before the externalId enrichment and whose space was already removed (manual cleanup).
- Recursive scope deletion (space scopes have no children).
- Modifying the `validateNoAccidentalFullDeletion` safety check.

## Tasks

1. **Enrich externalId format** - Update `ScopeManagementService.ensureSpaceScopes()` to include spaceId in the externalId. Change the method signature to accept a spaceKey-to-spaceId mapping. Always update externalId (not just when missing) to migrate existing scopes. Update `EXTERNAL_ID_PREFIX` usage and add a parsing utility.

2. **Add space cleanup to ScopeManagementService** - Add a new method (e.g., `cleanupRemovedSpaces()`) that lists scope children, detects orphaned spaces by comparing against discovered spaceKeys, and deletes their files and scopes. Includes error handling per-space.

3. **Integrate cleanup into synchronize()** - Call the new cleanup method from `ConfluenceSynchronizationService.synchronize()` after the existing sync flow. Pass the discovered spaceKeys and necessary config (tenantName, useV1KeyFormat) for partialKey reconstruction.

4. **Write tests** - Behavioral tests for externalId parsing, orphan detection, cleanup flow, externalId migration, and edge cases.
