# Design: Confluence Sync Page Discovery & Content Fetching

**Ticket:** UN-16935

## Problem

The confluence connector v2 has all infrastructure in place (multi-tenancy, auth, API client with Cloud/Data Center adapters, scheduler) but the sync service is a stub. The scheduler fires `synchronize()` which only acquires a token and logs. We need to implement the actual scanning logic that discovers Confluence pages marked for ingestion and fetches their content.

This is the core value of the connector — without it, the service runs but does nothing useful. The v1 connector has this logic in a monolithic `ConfluenceScanner` class. We need to port the same behavior into v2's cleaner architecture, using the existing `ConfluenceApiClient` methods.

**Scope:**
- Discover pages with ingest labels via CQL search
- Recursively expand children for pages with the "ingest all" label
- Fetch full page content (body, labels, space metadata)
- Log results; no ingestion upload yet
- Respect `maxPagesToScan` config for testing
- Skip databases (no body content in API)

## Solution

### Overview

Introduce two new classes (`ConfluencePageScanner` and `ConfluencePageProcessor`) that split the sync flow into discovery and content fetching. The existing `ConfluenceSynchronizationService` orchestrates them. This mirrors v1's two-phase approach (lightweight discovery first, full content fetch second) but with proper separation of concerns.

The scanner uses the existing `ConfluenceApiClient.searchPagesByLabel()` and `getChildPages()` methods — no new API calls needed. The processor uses `getPageById()` to fetch full content. Both classes are instantiated per-tenant via the `ServiceRegistry`.

### Architecture

**New types:**

```typescript
interface DiscoveredPage {
  id: string;
  title: string;
  type: ContentType;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  versionTimestamp: string;
  webUrl: string;
  labels: string[];
}

interface ProcessedPage {
  id: string;
  title: string;
  body: string;
  webUrl: string;
  spaceId: string;
  spaceKey: string;
  spaceName: string;
  metadata?: { confluenceLabels: string[] };
}
```

**ConfluencePageScanner:**
1. Calls `apiClient.searchPagesByLabel()` to get all labeled pages (lightweight, no body)
2. For each page, checks if it has the "ingest all" label
3. If yes, recursively calls `apiClient.getChildPages(parentId, contentType)` to expand children
4. Collects all discovered pages into a flat list of `DiscoveredPage` objects
5. Respects `maxPagesToScan` limit from processing config
6. Skips databases (no body content)

**ConfluencePageProcessor:**
1. Takes a list of `DiscoveredPage` references
2. For each page, calls `apiClient.getPageById(id)` which fetches `body.storage`
3. Extracts: HTML body, labels (excluding ingest labels, sorted alphabetically), space metadata
4. Builds `ProcessedPage` DTOs
5. Logs each processed page (ingestion upload is a future ticket)
6. Skips pages with empty body

**ConfluenceSynchronizationService (modified):**
```
synchronize():
  1. Acquire auth token (already exists)
  2. scanner.discoverPages() -> DiscoveredPage[]
  3. Log discovery summary (count, spaces)
  4. processor.processPages(discoveredPages) -> ProcessedPage[]
  5. Log processing summary
```

Both `ConfluencePageScanner` and `ConfluencePageProcessor` receive `ConfluenceApiClient` and config through the `ServiceRegistry`, following the same pattern as existing services.

### Error Handling

**Scanner errors:**
- `searchPagesByLabel()` failure: Propagates to `synchronize()` try/catch, aborts sync cycle. Correct because if search fails there's nothing to do.
- `getChildPages()` failure for a specific parent: Log warning, skip that parent's children, continue with other pages. One broken page tree shouldn't block the entire sync.
- Databases: Silently excluded during discovery (info-level log).

**Processor errors:**
- `getPageById()` failure for a specific page: Log warning, skip that page, continue with next. Matches v1 pattern of "possibly deleted in the meantime."
- Pages with no body: Log at info level, skip.
- If all pages fail: Sync still completes from orchestrator perspective. Individual errors visible in logs.

**Principle:** Individual page failures are logged and skipped. Infrastructure failures (auth, search endpoint) abort the sync cycle.

### Testing Strategy

Tests are the final implementation task. Behavioral tests using Vitest with mocked `ConfluenceApiClient`:

**Scanner tests:** Discovers labeled pages; recursively expands "ingest all" children; respects `maxPagesToScan`; skips databases; handles child fetch failures gracefully; handles empty results.

**Processor tests:** Fetches content; strips ingest labels and sorts remaining; skips empty body pages; skips null (deleted) pages; builds correct DTOs.

**Sync service tests (extend existing):** Orchestrates scanner then processor; logs summaries.

## Out of Scope

- File-diff / incremental sync (every cycle processes all labeled pages)
- Ingestion upload to Unique platform
- File attachment extraction and download
- Concurrent page processing (`processing.concurrency` config unused for now)
- Single-page sync endpoint
- Scope/content deletion endpoints

## Tasks

1. **Define sync types** — Create `DiscoveredPage` and `ProcessedPage` interfaces in the synchronization module. These are the data contracts between scanner, processor, and future ingestion upload.

2. **Implement ConfluencePageScanner** — New class that discovers labeled pages via `searchPagesByLabel()` and recursively expands children for "ingest all" pages. Returns a flat `DiscoveredPage[]`. Respects `maxPagesToScan`. Skips databases. Handles child-fetch errors gracefully.

3. **Implement ConfluencePageProcessor** — New class that fetches full content for discovered pages via `getPageById()`. Extracts body, labels (excluding ingest labels), space metadata. Returns `ProcessedPage[]`. Skips empty/null pages.

4. **Wire up ConfluenceSynchronizationService** — Modify the existing stub to create scanner and processor, call discovery then processing, and log summaries. Register new classes in the tenant's service map during `TenantRegistry` initialization.

5. **Write tests** — Behavioral tests for scanner, processor, and sync service orchestration. Mock `ConfluenceApiClient`. Cover happy paths, edge cases (empty results, databases, child-fetch failures, null pages, empty body).
