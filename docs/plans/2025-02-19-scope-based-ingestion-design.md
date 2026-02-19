# Design: Scope-Based Ingestion for Confluence Connector v2

## Problem

The confluence-connector-v2 can discover Confluence pages via label-based CQL search and fetch their content, but does not ingest anything into Unique. We need to implement the full ingestion pipeline: file-diffing (comparing remote Confluence state vs what Unique already knows), ingesting new/updated pages and their linked files, and deleting removed content.

This iteration focuses on **scope-based (flat) ingestion** — all pages for a tenant go into a single configured `scopeId`. The Unique API calls will be mocked using a `MockUniqueApiClient` since the shared `@unique-ag/unique-api` package is not yet available on this branch.

The design must be forward-compatible with:
- **Recursive ingestion** (path-based, creating scope hierarchy matching Confluence's page tree) — coming next
- **Real `@unique-ag/unique-api` package** — replacing the mock when the shared package is merged

## Solution

### Overview

Three new services are introduced into the existing architecture:

1. **FileDiffService** — Takes `DiscoveredPage[]` from the scanner, transforms them to `FileDiffItem[]`, and calls the Unique API's `performFileDiff()` to determine new, updated, and deleted pages.

2. **IngestionService** — Handles the per-page ingestion cycle (register content → upload HTML body → finalize) and per-file cycle (register → stream from source → finalize). Also handles content deletion for removed pages.

3. **MockUniqueApiClient** — Implements the `UniqueApiClient` interface surface from `@unique-ag/unique-api` with stub methods that log calls and return plausible fake data. Will be swapped for the real package later.

The existing `ConfluenceSynchronizationService` orchestrates the full flow:
1. `scanner.discoverPages()` → `DiscoveredPage[]`
2. `fileDiffService.computeDiff(discoveredPages)` → `{ newPageIds, updatedPageIds, deletedPageIds }`
3. For new + updated: `contentFetcher.fetchPagesContent(pages)` → `FetchedPage[]`
4. For each fetched page: `ingestionService.ingestPage(page)` — register, upload HTML buffer, finalize
5. For each page's linked files (if file ingestion enabled): `ingestionService.ingestFile(...)` — register, stream from source URL to writeUrl, finalize
6. For deleted: `ingestionService.deletePages(deletedPageIds)`

### Tenant Config Extension

A new `ingestion` section is added to the tenant YAML config:

```yaml
ingestion:
  ingestionMode: flat          # 'flat' | 'recursive' (only flat implemented now)
  scopeId: "some-scope-id"    # Required — root scope for ingestion
  ingestFiles: enabled         # 'enabled' | 'disabled'
  allowedFileExtensions:       # Required when ingestFiles is enabled
    - pdf
    - docx
    - xlsx
```

A new `IngestionConfigSchema` (Zod) validates this section. For `flat` mode, `scopeId` is required. The `recursive` mode (future) will use `scopeId` as the root scope.

`sourceKind` is derived from the existing `confluence.instanceType`:
- `cloud` → `ATLASSIAN_CONFLUENCE_CLOUD`
- `data-center` → `ATLASSIAN_CONFLUENCE_ONPREM`

`sourceName` is derived from `confluence.baseUrl`.

### Architecture

#### FileDiffService

Transforms `DiscoveredPage[]` to `FileDiffItem[]`:
- `key`: Confluence page ID (globally unique within an instance)
- `url`: page web URL (from `DiscoveredPage.webUrl`)
- `updatedAt`: `DiscoveredPage.versionTimestamp`

When file ingestion is enabled, also includes linked files from page HTML bodies in the diff list:
- `key`: `{pageId}_{filename}`
- `url`: the file's source URL
- `updatedAt`: same as parent page's version timestamp

Calls `performFileDiff()` with:
- `partialKey`: `{confluenceBaseUrl}` (namespace prefix for scope-based mode)
- `sourceKind`: derived from `confluence.instanceType`
- `sourceName`: `confluence.baseUrl`

Safety check: if file-diff returns deletions for ALL currently known content and zero new/updated items, abort the sync to prevent accidental full-scope wipe (same pattern as SharePoint's `validateNoAccidentalFullDeletion`).

#### IngestionService

**Page ingestion** (for each `FetchedPage`):
1. Convert HTML body to `Buffer`
2. Call `registerContent()` with:
   - `key`: `{confluenceBaseUrl}/{pageId}`
   - `title`: page title
   - `mimeType`: `text/html`
   - `scopeId`: from tenant ingestion config
   - `sourceKind` / `sourceName`: derived from confluence config
   - `url`: page web URL
   - `byteSize`: byte length of HTML buffer
   - `metadata`: `{ confluenceLabels: [...], spaceKey, spaceName }`
   - `storeInternally`: true
3. Upload buffer to `writeUrl` (PUT with `Content-Type: text/html`, `x-ms-blob-type: BlockBlob`)
4. Call `finalizeIngestion()` with `readUrl`

**File ingestion** (for each linked file):
1. Call `registerContent()` with:
   - `key`: `{confluenceBaseUrl}/{pageId}_{filename}`
   - `mimeType`: determined from file extension
   - `byteSize`: from HTTP HEAD or stream content-length
2. Stream file from source URL directly to `writeUrl` (no disk download)
3. Call `finalizeIngestion()` with `readUrl`

**Content deletion**:
- Call `files.deleteByIds()` for deleted page IDs from file-diff

#### MockUniqueApiClient

Implements the `UniqueApiClient` interface with:
- `ingestion.performFileDiff()` → returns all submitted keys as `newFiles`, empty arrays for rest
- `ingestion.registerContent()` → returns fake `IngestionApiResponse` with mock write/read URLs
- `ingestion.finalizeIngestion()` → returns `{ id: "mock-content-id" }`
- `files.deleteByIds()` → returns count of submitted IDs
- All methods log their calls for debugging visibility

Only the facades needed for ingestion (`ingestion`, `files`) need implementations. Others (`scopes`, `users`, `groups`, `auth`) can throw "not implemented" for now.

### Error Handling

**File-diff errors**: If the file-diff call fails, the sync cycle aborts for that tenant. No partial processing.

**Safety check**: If file-diff returns deletions for all pages and no new/updated pages, abort to prevent accidental full-scope wipe.

**Per-page ingestion errors**: If registration, upload, or finalization fails for a page, log the error and skip that page. Continue with other pages. Next sync cycle will pick it up via file-diff.

**Per-file streaming errors**: If a linked file fails to download/stream, log and skip. The page content itself is still ingested.

**Deletion errors**: If a page deletion fails, log and continue. Next cycle's file-diff will still show it as "to delete."

**Concurrency**: The existing `processing.concurrency` config controls parallel page ingestion. `processing.stepTimeoutSeconds` applies to each page's ingestion cycle.

### Testing Strategy

Behavioral tests using vitest + `@suites/unit` TestBed:

**FileDiffService**: Correct transformation of DiscoveredPage to FileDiffItem, correct parameters passed to performFileDiff, empty list handling, accidental deletion safety check.

**IngestionService**: Correct ContentRegistrationRequest mapping from FetchedPage, upload with proper buffer and headers, finalization with readUrl, empty body skip, error handling per page, deletion call for removed pages, file streaming for linked files.

**ConfluenceSynchronizationService (updated)**: Full flow integration (discover → diff → fetch → ingest → delete), no-change handling, file-diff failure handling.

## Out of Scope

- **Recursive (path-based) ingestion** — separate follow-up work
- **Confluence native attachments** (`type=attachment`) — only linked files in page HTML are handled
- **Real `@unique-ag/unique-api` integration** — using mock for now
- **Page comments or version history ingestion**
- **Scope creation/management** — flat mode uses a single pre-configured scope
- **Permissions sync**

## Tasks

1. **Add ingestion config schema** — Create `IngestionConfigSchema` with Zod (ingestionMode, scopeId, ingestFiles, allowedFileExtensions). Add to `TenantConfigSchema`. Add `IngestionSourceKind` constant derived from `confluence.instanceType`. Update example tenant configs.

2. **Create MockUniqueApiClient** — Implement the `UniqueApiClient` interface with mock `ingestion` and `files` facades. `performFileDiff` returns all keys as new. `registerContent` returns fake write/read URLs. `finalizeIngestion` returns fake ID. `deleteByIds` returns count. Log all calls. Register in `ServiceRegistry` per tenant.

3. **Create FileDiffService** — Transform `DiscoveredPage[]` to `FileDiffItem[]` (key=pageId, url=webUrl, updatedAt=versionTimestamp). Include linked file entries when file ingestion is enabled (parse HTML for href, filter by allowed extensions). Call `performFileDiff` via MockUniqueApiClient. Implement accidental full-deletion safety check. Return categorized page ID lists.

4. **Create IngestionService** — Implement page ingestion cycle: build `ContentRegistrationRequest` from `FetchedPage`, convert HTML body to Buffer, register → upload to writeUrl → finalize with readUrl. Implement file ingestion: register → stream from source URL to writeUrl → finalize. Implement `deletePages` via `files.deleteByIds`. Handle per-page and per-file errors gracefully (log and skip).

5. **Update ConfluenceSynchronizationService** — Wire FileDiffService and IngestionService into the sync flow. After discovery, call file-diff. Fetch content only for new+updated pages. Ingest pages and their linked files. Delete removed content. Use `processing.concurrency` for parallel ingestion.

6. **Update TenantRegistry** — Register FileDiffService, IngestionService, and MockUniqueApiClient in the per-tenant service initialization.

7. **Write tests** — Behavioral tests for FileDiffService, IngestionService, and the updated ConfluenceSynchronizationService using vitest + @suites/unit TestBed.
