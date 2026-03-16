# Design: Deletion Guard Key Format Check

## Problem

The Confluence connector's `validateNoAccidentalFullDeletion` guard in `FileDiffService` always blocks when `deletedFiles.length === totalFilesInUnique`, even when genuinely new files are being added alongside deletions. This causes spaces to get permanently stuck when a user deletes all pages and uploads new ones — the stale pages can never be removed because the guard always fires.

This is the same bug that was fixed in the SharePoint connector on 2026-03-13 (commit `fd8c8d39`).

## Solution

### Overview

When the guard detects that all files in Unique would be deleted, instead of always blocking, compare the submitted keys against the deleted keys:

- If deleted keys overlap with submitted keys → likely a **key format bug** (same items appear as both "new" and "deleted") → **block**
- If no overlap AND there are new files → **legitimate content replacement** → **allow** with a warning log
- If no overlap AND no new files → **block** (no new content to replace with)

Since Confluence keys are simple page IDs (e.g. `"p-1"`) with no prefix, we compare keys directly — no extraction helper needed.

### Architecture

The change is entirely within `FileDiffService.validateNoAccidentalFullDeletion`. The method signature stays the same but it also needs access to `diffResponse.newFiles` to check if new files are being added. We'll pass the full `diffResponse` instead of just using it partially.

The guard already receives `submittedItems: FileDiffItem[]` (which have `.key`) and `diffResponse: FileDiffResponse` (which has `.deletedFiles` and `.newFiles`).

Logic change in the `deletedFiles.length === totalFilesInUnique` branch:

```
submittedKeys = Set of submittedItems.map(item => item.key)
deletedKeysOverlap = diffResponse.deletedFiles.some(key => submittedKeys.has(key))

if (no new files OR deletedKeysOverlap):
  → BLOCK (error log + assert.fail) — include deletedKeysOverlap in log
else:
  → ALLOW (warn log noting legitimate content replacement)
```

### Error Handling

- Block path: same as today — `logger.error` + `assert.fail` with descriptive message. Add `deletedKeysOverlap` to the log payload for debugging.
- Allow path: `logger.warn` with message noting how many files are being deleted and how many new files are being added.

### Testing Strategy

Update the existing test file `src/synchronization/__tests__/file-diff.service.spec.ts`:

1. **New ALLOWED test**: "should allow when all files are deleted but new files with different IDs are being added" — submitted keys `["p-1", "p-2"]`, deleted keys `["p-old-1"]`, totalFilesInUnique = 1, newFiles = `["p-1", "p-2"]` → should not throw.

2. **New BLOCKED test**: "should block when all files are deleted and new files share IDs with deleted keys (key format bug)" — submitted keys `["p-1", "p-2"]`, deleted keys `["p-1", "p-2"]`, totalFilesInUnique = 2, newFiles = `["p-1", "p-2"]` → should throw.

3. **Update existing BLOCKED test** ("should abort when file diff would delete all files stored in Unique"): This test has `newFiles: ['p-1']` and `deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3']` with no ID overlap — under the new logic this would be ALLOWED, not blocked. Fix: change `newFiles` to `[]` so it still tests the "no new files" block path.

4. **Update existing BLOCKED test** ("should abort when key format changed causing full replacement"): Has `newFiles: ['p-1', 'p-2', 'p-3']` and `deletedFiles: ['p-old-1', 'p-old-2', 'p-old-3']` — no ID overlap, so under new logic this would be ALLOWED. Fix: change deleted keys to `['p-1', 'p-2', 'p-3']` so they overlap with submitted keys, testing the key format bug detection path.

## Out of Scope

- No `extractPageId` helper — keys are simple IDs, YAGNI
- No changes to `buildFileDiffItems` or key format
- No changes to the first guard (zero submitted items)

## Tasks

1. **Update `validateNoAccidentalFullDeletion` in `file-diff.service.ts`** - Add key overlap detection logic in the `deletedFiles.length === totalFilesInUnique` branch. Block when no new files or keys overlap; allow with warning when genuinely new files are added.

2. **Fix existing tests that will break** - Update the two existing BLOCKED tests whose assertions change under the new logic (the ones with non-overlapping new/deleted keys that would now be allowed).

3. **Add new test cases** - Add "allowed: genuinely new files" and "blocked: key format bug with ID overlap" test cases to the spec file.
