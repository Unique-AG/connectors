# UN-18259 — Delete files when a Confluence space is deleted

## Context

When a Confluence space is fully deleted (or every page in it loses the sync label), the connector leaves the corresponding files orphaned in Unique forever.

`FileDiffService.computeDiff()` in `services/confluence-connector/src/synchronization/file-diff.service.ts` only iterates over spaces that have at least one discovered page or attachment. A space with zero discovered items never enters the loop, so `performFileDiff` is never invoked for it and its files are never marked for deletion.

There is already a partial cleanup in `ScopeManagementService.cleanupRemovedSpaces()` that calls `files.deleteByKeyPrefix(partialKey)` and then deletes the scope. The gap is twofold:

1. It only catches spaces whose **scope** still exists as a child of the root scope and whose `externalId` parses correctly. Files whose scope has already been deleted, or whose scope is registered with an unparseable `externalId`, stay orphaned.
2. It deletes files via `files.deleteByKeyPrefix` rather than going through the canonical ingestion deletion pipeline (`performFileDiff` → `deleteContentByKeys`). Running deletion through the diff endpoint is the contract the rest of the connector uses and is what the ticket explicitly asks for.

This change closes both gaps by routing orphan-space deletion through the file-diff API, mirroring what `sharepoint-connector` does for `processSiteDeletions` (direct call to delete content for a site that no longer exists).

## Approach

After the per-space diff loop in `FileDiffService.computeDiff()`, enumerate spaces still represented in Unique, subtract the spaces we discovered this run, and for each remaining "orphan space" submit an empty `fileList` to `performFileDiff` with the existing accidental-full-deletion guard explicitly bypassed. The returned `deletedFiles` flow into the existing `FileDiffResult.deletedItems`, so downstream processing in `ConfluenceSynchronizationService.synchronize()` (which already calls `ingestionService.deleteContentByKeys`) handles the actual deletion with no further changes.

`ScopeManagementService.cleanupRemovedSpaces()` keeps its scope-deletion responsibility but stops deleting files itself — files are now removed by the diff pipeline before scope cleanup runs. This avoids double-deletion and keeps a single deletion path.

### Source of stored space list

Use `uniqueApiClient.scopes.listChildren(this.ingestionConfig.scopeId)` (the call `cleanupRemovedSpaces` already makes) and parse each child's `externalId` with the existing `parseScopeExternalId()` to recover `{ spaceId, spaceKey }`. For each parseable child whose `spaceKey` is not in the discovered set, build a `partialKey` via the existing `buildPartialContentKey(tenantName, spaceId, spaceKey, useV1KeyFormat)` and submit an empty diff.

This intentionally does not try to discover "files with no scope at all" — those are a separate (rarer) data-integrity concern not in the scope of this ticket. Children with unparseable `externalId` continue to log a warning, same as today.

### Guard bypass

The existing guard inside `computeDiff` rejects an empty submission whenever `deletedFiles.length > 0`. Rather than adding a flag to that method, factor the per-space diff submission into a small helper that accepts an `allowFullDeletion: boolean` option and call it with `true` from the orphan-space path. The check that runs `getCountByKeyPrefix` (Check 2) is still useful even for orphan deletion — but it must allow the case `deletedFiles.length === totalFilesInUnique && fileList.length === 0` instead of asserting on it. The new option suppresses Check 1 entirely and bypasses Check 2's `assert.fail` for this exact pattern.

### Discovery-failure safety net

The current discovery already has the safety check at `cleanupRemovedSpaces:155` that aborts cleanup when `discoveredSpaceKeys.size === 0` (treating it as a likely Confluence outage). Replicate the same guard at the start of the new orphan-diff step in `computeDiff`. If the connector discovered zero spaces this run, do **not** treat every stored space as orphan — log and skip orphan diffing.

## Files to change

### `services/confluence-connector/src/synchronization/file-diff.service.ts`

- Inject `Scope` lookup capability. Easiest: add a constructor param for a callback `getStoredSpaces: () => Promise<Array<{ spaceId: string; spaceKey: string }>>` provided by the orchestrator, or just inject the scope-management helper. Prefer passing a callback to keep `FileDiffService` decoupled from `ScopeManagementService`.
- Extract the body of the per-space diff (lines 48–79) into a private helper `runDiffForSpace(partialKey, fileDiffItems, { allowFullDeletion })` that:
  - calls `performFileDiff`
  - calls `validateNoAccidentalFullDeletion(submittedItems, response, partialKey, { allowFullDeletion })`
  - returns the response.
- After the existing loop in `computeDiff`, call the new `getStoredSpaces` callback, compute the set difference against `allSpaceKeys`, and for each orphan space submit an empty diff via `runDiffForSpace(partialKey, [], { allowFullDeletion: true })`. Push results into `result.deletedItems` with the orphan space's `partialKey`. Skip if `discoveredPages` and `discoveredAttachments` are both empty (mirrors the existing scope-cleanup guard).
- Update `validateNoAccidentalFullDeletion` to accept `{ allowFullDeletion }`. When true: skip Check 1, and inside Check 2 when both submitted is empty and the response equals the count, log a structured warning ("intentional full-space deletion") instead of `assert.fail`. The deletedKeysOverlap branch is impossible with empty submitted items, so the existing safety against key-format bugs is unaffected.

### `services/confluence-connector/src/synchronization/confluence-synchronization.service.ts`

- When constructing/calling `FileDiffService`, supply the `getStoredSpaces` callback. Implementation: `() => this.scopeManagementService.listStoredSpaces()` (new method, see below).
- No changes to deletion handling — the orphan files come back in `diffResult.deletedItems` and flow through the existing `ingestionService.deleteContentByKeys` step at lines 101–109.

### `services/confluence-connector/src/synchronization/scope-management.service.ts`

- Add a public `listStoredSpaces(): Promise<Array<{ scope: Scope; parsed: ParsedExternalId }>>` that is just the parseable subset of `listChildren(rootScopeId)`. Reuse `parseScopeExternalId` and the warn-on-unparseable behavior already in `identifyOrphanedScopes` (lines 210–233) — refactor to share that walk.
- In `cleanupRemovedSpaces`, **remove** the `files.deleteByKeyPrefix(partialKey)` call (file deletion now runs via diff before this point). Keep the scope deletion and metrics. Update the log message and the orphan-files metric: either drop `recordOrphanedFilesCleaned` here or keep it but record `0` (deletion is logged elsewhere). Recommended: drop it from this site and emit it from the new diff path so the metric still reflects orphan-file deletions, just attributed to the diff step.
- Keep the empty-discovery guard (`discoveredSpaceKeys.size === 0`) — it now protects scope deletion only.

### Tests

- `services/confluence-connector/src/synchronization/__tests__/file-diff.service.spec.ts`
  - Add cases:
    - Orphan space present in stored list but not discovered → empty diff submitted with `partialKey`, `deletedFiles` from response appear in `result.deletedItems` with that partialKey, guard does **not** throw.
    - Orphan space + zero items submitted + zero stored count (race: scope existed but files already gone) → no error, no deletions emitted.
    - Discovery returned empty (`discoveredPages.length === 0 && discoveredAttachments.length === 0`) → orphan-diff step is skipped entirely; no `performFileDiff` called for orphans.
    - Existing guard tests (lines 542–641) still pass: confirm `allowFullDeletion: false` (default) preserves all current abort paths.
- `services/confluence-connector/src/synchronization/__tests__/scope-management.service.spec.ts`
  - Update existing `cleanupRemovedSpaces` tests: assertion that `deleteByKeyPrefix` is called must be removed; assert it is **not** called.
  - Add a test for new `listStoredSpaces` exposing parseable children only and warning on unparseable ones.

## Out of scope

- Discovering orphaned files that have no corresponding scope at all (would require a tenant-wide key scan and is not what this ticket asks for).
- Migrating v1-keyed orphans (handled the same way as v2 since `buildPartialContentKey` already branches on `useV1KeyFormat`).
- Adding a feature flag — sharepoint does not gate the equivalent path and the existing accidental-deletion guards already protect against discovery failures.

## Verification

1. Unit: `pnpm --filter confluence-connector test src/synchronization/__tests__/file-diff.service.spec.ts` and `…/scope-management.service.spec.ts` pass; new cases cover orphan-space deletion and guard bypass.
2. Type & lint: `pnpm --filter confluence-connector tsc --noEmit` and `pnpm biome check services/confluence-connector` clean.
3. Manual / integration scenario (against a dev tenant):
   - Sync a Confluence with two labeled spaces. Confirm files for both ingest.
   - Remove the sync label from every page in space B (or delete space B). Re-run sync.
   - Expect: log line for orphan-space diff submission with `partialKey` for space B, downstream `deleteContentByKeys` removes those files, scope for space B deleted afterwards. Files for space A untouched.
   - Negative case: simulate Confluence discovery failure (zero spaces returned). Expect: orphan-diff step skipped, no deletions, sync logs the same warning that scope cleanup logs today.
4. Metrics: verify `recordOrphanedFilesCleaned` (or its diff-path equivalent) reports the deletion count for the deleted space.

## Critical files

- `services/confluence-connector/src/synchronization/file-diff.service.ts` — orphan-diff loop and guard option
- `services/confluence-connector/src/synchronization/confluence-synchronization.service.ts` — wires callback
- `services/confluence-connector/src/synchronization/scope-management.service.ts` — exposes `listStoredSpaces`, drops file deletion from `cleanupRemovedSpaces`
- `services/confluence-connector/src/synchronization/__tests__/file-diff.service.spec.ts` — new cases
- `services/confluence-connector/src/synchronization/__tests__/scope-management.service.spec.ts` — updated assertions
- Reused (no edits): `services/confluence-connector/src/utils/key-format.ts` (`buildPartialContentKey`), `services/confluence-connector/src/synchronization/scope-external-id.ts` (`parseScopeExternalId`), `packages/unique-api/src/ingestion/ingestion.service.ts` (`performFileDiff`), `packages/unique-api/src/files/files.service.ts` (`getCountByKeyPrefix`).
