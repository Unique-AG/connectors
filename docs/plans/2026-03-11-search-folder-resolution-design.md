# Design: Search Folder ID Resolution

## Problem

The `directories` search condition in `SearchEmailsQuery` accepts folder IDs (`providerDirectoryId` values from the Microsoft Graph API). LLMs calling this tool may hallucinate folder IDs — providing display names like `"Inbox"` or arbitrary strings instead of valid IDs like `AAMkAGQ3...`. These pass through unvalidated, silently producing wrong or empty results with no explanation to the LLM.

## Solution

### Overview

Add a folder resolution step inside `SearchEmailsQuery.run()` before building the metadata filter. Each provided folder reference is validated against the user's `directories` rows: first by exact `providerDirectoryId` match, then by fuzzy display name match (Levenshtein similarity ≥ 80%). Unrecognized references are discarded and reported back to the LLM via a markdown `searchSummary` string.

The return type changes from `SearchEmailResult[]` to `{ results: SearchEmailResult[], searchSummary: string | undefined }`, where `searchSummary` is `undefined` when no folders were discarded.

### Architecture

All new logic lives inside `SearchEmailsQuery` — no new files or services.

**`search-emails.query.ts`:**
- Import `directories` table from `~/db`
- Add `fastest-levenshtein` dependency for similarity computation
- Add private `resolveFolderConditions(rawIds: string[], folders: DirectoryRow[])` method returning `{ resolvedIds: string[], unrecognized: string[] }`
- Update `run()` to query `directories` for the user's folders, call resolution before `buildSearchFilter`, mutate the conditions, and return the new shape
- Update return type

**MCP tool that calls `run()`:**
- Destructure `{ results, searchSummary }` from the query result
- Surface `searchSummary` in the tool's text response so the LLM sees it

`buildSearchFilter` and `SearchEmailsInputSchema` are unchanged.

### Resolution Logic

For each raw folder reference:
1. Exact match against `providerDirectoryId` → keep as-is
2. No exact match → compare lowercased input against lowercased `displayName` for all folders using Levenshtein distance; pick the closest match if similarity ≥ 80% → replace with correct `providerDirectoryId`
3. No match → discard, record as unrecognized

Similarity formula: `1 - (distance / Math.max(a.length, b.length))`

### Error Handling

- DB query failure → bubbles up (consistent with existing assertions in `run()`)
- All folder IDs unrecognized → remove `directories` condition entirely; search runs across all folders
- Some unrecognized → keep resolved ones, discard the rest
- `searchSummary` markdown format:
  ```
  > **Note:** The following folder(s) were not recognized and were excluded from the search: `"foo"`, `"bar"`. The search ran across all available folders instead.
  ```

### Testing Strategy

`resolveFolderConditions` is a pure function and should be unit tested in isolation:
- Exact `providerDirectoryId` match returns the ID unchanged
- Display name fuzzy match (≥ 80% similarity) returns the correct `providerDirectoryId`
- Below-threshold string is discarded and returned as unrecognized
- Mixed input: some matched, some not — correct split
- All unrecognized → empty `resolvedIds`, all in `unrecognized`

## Out of Scope

- Resolving folder references in any condition other than `directories`
- Hierarchical folder expansion (matching a parent and including children)
- Caching the folder list between calls
- Surfacing fuzzy-matched folder names back to the LLM (only unrecognized ones are reported)

## Tasks

1. **Install `fastest-levenshtein`** - Add the package as a dependency to the `outlook-semantic-mcp` service's `package.json`.

2. **Add `resolveFolderConditions()` to `SearchEmailsQuery`** - Private method taking raw folder ID strings and the user's directory rows, returning `{ resolvedIds: string[], unrecognized: string[] }` using exact match then fuzzy match via `fastest-levenshtein` at ≥ 80% similarity on lowercased display names.

3. **Wire resolution into `run()` and update return type** - Query the `directories` table for the user's folders, call `resolveFolderConditions`, mutate the conditions before `buildSearchFilter`, build the markdown `searchSummary` for any unrecognized folders, and return `{ results, searchSummary }`.

4. **Update the MCP tool caller** - Find the tool that invokes `SearchEmailsQuery.run()` and update it to handle the new return shape, surfacing `searchSummary` in the tool response.

5. **Unit test `resolveFolderConditions`** - Cover exact match, display name fuzzy match, below-threshold discard, mixed input, and all-unrecognized scenarios.
