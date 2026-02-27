# Design: Remove file ingestion and pre-resolve scopes

## Problem

The `IngestionService` owns two concerns it shouldn't:

1. **Scope management** — it calls `scopeManagementService.ensureSpaceScope()` per-page during ingestion, coupling it to scope lifecycle. The SharePoint connector keeps these separate: scopes are resolved upfront via `createFromPaths` and `scopeId` is passed as a parameter.

2. **File attachment ingestion** — `ingestFiles()` and its helpers (`streamToWriteUrl`, `getRemoteFileSize`, `getMimeType`, `extractFilename`) along with config fields (`ingestFiles`, `allowedFileExtensions`) add complexity for a feature that isn't needed yet. This also bleeds into `FileDiffService`, the sync service, config schema, Helm chart values, and utilities.

## Solution

### Overview

Two independent changes:

**Remove file ingestion entirely.** Delete `ingestFiles()` and all supporting code: private helpers in `IngestionService`, the `IngestFiles` enum, `MIME_TYPES`/`DEFAULT_MIME_TYPE` constants, `extractFileUrls` utility (`html-link-parser.ts`), file extraction logic in `FileDiffService`, file ingestion branching in the sync service, config schema fields (`ingestFiles`, `allowedFileExtensions`) and their Helm chart counterparts.

**Pre-resolve scopes and pass `scopeId` as a parameter.** Add `ensureSpaceScopes(spaceKeys[])` to `ScopeManagementService` that batch-resolves all space scopes via `createFromPaths`. Remove `scopeManagementService` from `IngestionService`. Change `ingestPage(page)` to `ingestPage(page, scopeId)`. The sync service collects unique space keys, batch-resolves them, and passes `scopeId` to each ingestion call.

### Architecture

**ScopeManagementService** gains one new method:

```ts
public async ensureSpaceScopes(spaceKeys: string[]): Promise<Map<string, string>>
```

It deduplicates input, builds paths (`${rootScopePath}/${spaceKey}`), calls `createFromPaths` in one batch, sets `externalId` for each scope via `updateExternalId`, and returns `Map<spaceKey, scopeId>`. The existing `ensureSpaceScope` (singular) remains for potential standalone use.

**IngestionService** becomes scope-unaware:
- Constructor drops `scopeManagementService`
- `ingestPage(page, scopeId)` receives scopeId directly

**ConfluenceSynchronizationService** orchestrates the new flow:
1. `scopeManagementService.initialize()` — build root path
2. `scanner.discoverPages()` → `fileDiffService.computeDiff()` → `contentFetcher.fetchPagesContent()`
3. Collect unique spaceKeys from fetched pages
4. `scopeManagementService.ensureSpaceScopes(uniqueKeys)` — one batch call
5. `ingestPagesWithConcurrency(fetchedPages, spaceScopes, concurrency)` — passes scopeId per page

### Error Handling

- `ensureSpaceScopes` throws if `initialize()` wasn't called (same guard as current `ensureSpaceScope`)
- If `createFromPaths` fails, the error propagates to `synchronize()` which catches and logs — sync aborts for this cycle
- Individual page ingestion errors remain caught per-page (existing `ingestPage` behavior)

### Testing Strategy

- Update existing behavioral tests — no new test files
- `scope-management.service.spec.ts`: Add tests for `ensureSpaceScopes()` batch method (happy path, dedup, externalId setting)
- `ingestion.service.spec.ts`: Remove `scopeManagementService` mock, pass `scopeId` string directly
- `confluence-synchronization.service.spec.ts`: Mock `ensureSpaceScopes()`, verify `ingestPage` called with `(page, scopeId)`
- Delete file-ingestion tests across all spec files

## Out of Scope

- Removing `ensureSpaceScope` (singular) — still valid for potential future use
- Changing `FileDiffService` to also stop using `ServiceRegistry` — separate concern
- Any changes to the SharePoint connector

## Tasks

1. **Remove file ingestion from IngestionService** — Delete `ingestFiles()`, `buildFileRegistrationRequest`, `streamToWriteUrl`, `getRemoteFileSize`, `getMimeType`, `extractFilename`. Remove unused imports (`Readable`, `MIME_TYPES`, `DEFAULT_MIME_TYPE`, `IngestionConfig`). Update `ingestion.service.spec.ts` to remove file-ingestion tests and the `ingestionConfig` setup.

2. **Remove file ingestion from config and constants** — Delete `IngestFiles` enum, `MIME_TYPES`, `DEFAULT_MIME_TYPE` from `ingestion.constants.ts`. Remove `ingestFiles`/`allowedFileExtensions` from `ingestion.schema.ts` and the `.refine()` validator. Update Helm chart `values.yaml`, `values.schema.json`, `templates/tenant-config.yaml`, and all CI value files. Update `tenant-config-loader.spec.ts` and `sync.fixtures.ts`.

3. **Remove file ingestion from FileDiffService and sync service** — Delete `extractLinkedFileItems`, `isFileIngestionEnabled`, remove `pageBodies` param from `computeDiff`. Simplify sync service to remove file ingestion branching (`fileIngestionEnabled`, `allowedExtensions`, `confluenceBaseUrl` variables; `ingestPageAndFiles` method). Delete `src/utils/html-link-parser.ts`. Update `file-diff.service.spec.ts` and `confluence-synchronization.service.spec.ts`.

4. **Add batch scope resolution and pass scopeId to ingestPage** — Add `ensureSpaceScopes()` to `ScopeManagementService`. Remove `scopeManagementService` from `IngestionService` constructor, add `scopeId` param to `ingestPage()`. Update sync service to pre-resolve scopes after fetching pages and pass them during ingestion. Update `TenantRegistry` wiring. Update all affected tests.
