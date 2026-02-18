# Design: Confluence Cloud & Data Center API Client

**Ticket:** UN-16936

## Problem

The V2 Confluence Connector has multi-tenancy infrastructure, authentication, configuration, and scheduling — but no Confluence API client. The `ConfluenceSynchronizationService.synchronize()` is a stub that only acquires a token. We need a client that can search pages by label, fetch page content, fetch child pages, and handle pagination and rate limiting for both Cloud and Data Center instances.

## Solution

### Overview

Implement a `ConfluenceApiClient` class that provides the public API for all Confluence REST interactions. The client uses composition to delegate instance-type-specific logic (URL construction, response parsing, child page fetching) to thin adapter classes — `CloudApiAdapter` for Cloud and `DataCenterApiAdapter` for Data Center.

A tenant is always either Cloud or Data Center, never both — so each tenant gets exactly one adapter. The factory selects the adapter based on `config.confluence.instanceType`.

Each tenant gets its own `ConfluenceApiClient` instance via the existing `ServiceRegistry` pattern. The client owns a **per-tenant Bottleneck rate limiter** configured from `config.confluence.apiRateLimitPerMinute`. This single rate limiter governs **all** Confluence HTTP requests for that tenant — search, page fetches, child page fetches, and the Cloud adapter's N+1 per-child fetches. Every request to Confluence flows through `makeRateLimitedRequest()`, which schedules via Bottleneck before executing.

The adapters are pure translation layers with no HTTP or rate-limiting concerns of their own. When the Cloud adapter needs to make additional HTTP calls (N+1 child page fetches), it receives the client's `makeRateLimitedRequest` as an injected function, ensuring those calls are also governed by the same per-tenant rate limiter.

### Architecture

#### File Structure

```
src/confluence-api/
├── confluence-api-client.ts              # Main client (rate limiter, HTTP, pagination, auth)
├── confluence-api-adapter.ts             # Abstract adapter interface
├── confluence-api-client.factory.ts      # Factory: config → client + correct adapter
├── adapters/
│   ├── cloud-api.adapter.ts              # Cloud URL/response/child-page logic
│   └── data-center-api.adapter.ts        # Data Center URL/response/child-page logic
└── types/
    └── confluence-api.types.ts           # Response DTOs, ConfluencePage, enums
```

#### ConfluenceApiClient (Main Class)

Managed per-tenant by `ServiceRegistry`. Constructor receives `ServiceRegistry` (for auth + logger) and `ConfluenceConfig` (for rate limit, base URL, and labels).

The client reads these config values from `ConfluenceConfig`:
- `apiRateLimitPerMinute` — Bottleneck reservoir size (e.g. `100`)
- `ingestSingleLabel` — label for single-page sync (e.g. `ai-ingest`)
- `ingestAllLabel` — label for recursive sync (e.g. `ai-ingest-all`)
- `baseUrl` — Confluence instance URL (passed to adapter for URL construction)

Public methods:
- `searchPagesByLabel(): AsyncGenerator<ConfluencePage>` — CQL search with automatic pagination. Labels are read from config, not passed as parameters. The CQL query is constructed by the client: `((label="{ingestSingleLabel}") OR (label="{ingestAllLabel}")) AND (space.type=global OR space.type=collaboration) AND type != attachment`
- `getPageById(pageId: string): Promise<ConfluencePage | null>` — Single page with body, version, space, labels
- `getChildPages(parentId: string, contentType: ContentType): AsyncGenerator<ConfluencePage>` — Direct children with auto-pagination (delegates to adapter)

Internal infrastructure:
- `makeRateLimitedRequest<T>(url: string): Promise<{ status: number; headers: Record<string, string>; body: T }>` — undici request with Bottleneck scheduling, auth header injection, 429 retry logic. **This is the single chokepoint for all Confluence HTTP traffic for the tenant.** All public methods and adapter callbacks route through it.
- Bottleneck limiter: reservoir = `apiRateLimitPerMinute`, refresh every 60s. One limiter per tenant instance.
- undici `request()` for HTTP calls
- Auth header from `ConfluenceAuth.acquireToken()` (existing service)

#### ConfluenceApiAdapter (Abstract)

Defines the variant interface:

```typescript
abstract class ConfluenceApiAdapter {
  abstract buildSearchUrl(cql: string, limit: number, start: number): string;
  abstract buildGetPageUrl(pageId: string, expand: string[]): string;
  abstract parseSinglePageResponse(body: unknown): ConfluencePage | null;

  // Returns the canonical web URL for a page in Confluence.
  // This is always the real Confluence URL (e.g. Cloud: {baseUrl}/wiki{webui}, DC: {baseUrl}/pages/viewpage.action?pageId={id}).
  // Scope vs path-based ingestion does NOT affect this URL — scope management is handled
  // separately by the synchronization layer, consistent with the SharePoint connector pattern.
  abstract buildPageWebUrl(page: ConfluencePage): string;

  // Fetches direct children of a parent page/folder/database.
  // contentType determines which endpoint to use (Cloud has separate endpoints per type;
  // DC uses a single endpoint regardless of type).
  // httpGet is injected by the client — this IS the client's makeRateLimitedRequest,
  // ensuring all child fetches go through the same per-tenant rate limiter.
  abstract fetchChildPages(
    parentId: string,
    contentType: ContentType,
    httpGet: <T>(url: string) => Promise<T>,
  ): AsyncGenerator<ConfluencePage>;
}
```

#### CloudApiAdapter

- Search URL: `{baseUrl}/wiki/rest/api/content/search?cql={cql}&expand=metadata.labels,version,space&limit={limit}&start={start}`
- Get page URL: `{baseUrl}/wiki/rest/api/content/search?cql=id={pageId}&expand=body.storage,version,space,metadata.labels`
- Parse page response: unwrap `results[0]` from search response
- Page web URL: `{baseUrl}/wiki{page._links.webui}` — always the canonical Confluence Cloud URL
- Child pages: V2 API with content-type-specific endpoints, then per-child CQL fetch for full metadata (N+1 pattern using injected `httpGet`):
  - Page parent: `/wiki/api/v2/pages/{id}/direct-children?limit=250`
  - Folder parent: `/wiki/api/v2/folders/{id}/direct-children?limit=250`
  - Database parent: `/wiki/api/v2/databases/{id}/direct-children?limit=250`
  - Per-child detail fetch: `/wiki/rest/api/content/search?cql=id={childId}&expand=metadata.labels,version,space` (no body expand — body is fetched separately during ingestion via `getPageById`)

#### DataCenterApiAdapter

- Search URL: `{baseUrl}/rest/api/content/search?cql={cql}&expand=metadata.labels,version,space&os_authType=basic&limit={limit}&start={start}`
- Get page URL: `{baseUrl}/rest/api/content/{pageId}?os_authType=basic&expand=body.storage,version,space,metadata.labels`
- Parse page response: direct object (no unwrapping)
- Page web URL: `{baseUrl}/pages/viewpage.action?pageId={id}` — always the canonical Data Center page URL
- Child pages: V1 API (`/rest/api/content/{id}/child/page?os_authType=basic&expand=metadata.labels,version,space`), full data returned directly
- Note: Data Center URLs include `os_authType=basic` query parameter required by the DC REST API

#### ConfluenceApiClientFactory

Creates `ConfluenceApiClient` with the correct adapter based on `config.confluence.instanceType`. Since a tenant is always one or the other, this is a one-time decision at tenant initialization:
- `cloud` → `CloudApiAdapter`
- `data-center` → `DataCenterApiAdapter`

Registered in `TenantRegistry` service initialization alongside `ConfluenceAuth`.

#### Types

```typescript
interface ConfluencePage {
  id: string;
  title: string;
  type: ContentType;
  space: { id: string; key: string; name: string };
  body?: { storage: { value: string } };
  version: { when: string };
  _links: { webui: string };
  metadata: { labels: { results: Array<{ name: string }> } };
}

enum ContentType {
  PAGE = 'page',
  FOLDER = 'folder',
  DATABASE = 'database',
}

interface PaginatedResponse<T> {
  results: T[];
  _links: { next?: string };
}
```

### Error Handling

- No custom error types — re-throw standard errors with contextual logging via `sanitizeError()`.
- **429 retry policy:** On HTTP 429, parse `Retry-After` header (seconds). Wait the specified duration, retry. Max 3 retries per request. Default 30s backoff if header missing. Log each retry attempt.
- All other HTTP errors: fail fast, log with tenant-scoped logger.
- Log Confluence rate limit response headers (`X-RateLimit-Remaining`, `X-RateLimit-Limit`) as warnings when present.
- Pagination: if a page fetch fails mid-pagination, throw (let the caller decide whether to use partial results).

### Testing Strategy

Unit tests for all components using existing test patterns (Vitest, `@suites/unit`):

- **ConfluenceApiClient tests:** Mock adapter and undici. Verify rate-limited request flow, pagination loop, auth header injection, 429 retry behavior.
- **CloudApiAdapter tests:** Verify URL construction, response parsing, N+1 child fetch logic (mock the injected `httpGet`).
- **DataCenterApiAdapter tests:** Verify URL construction, response parsing, direct child page response handling.
- **ConfluenceApiClientFactory tests:** Verify correct adapter selection based on config.

## Out of Scope

- Synchronization orchestration (separate ticket) — the client just fetches data.
- Unique API integration / ingestion calls.
- Content processing (HTML stripping, label extraction).
- File attachment handling.
- Proxy support (can be added later if needed).
- OpenTelemetry metrics for API calls (can be added later).

## Tasks

1. **Define types and adapter interface** — Create `confluence-api.types.ts` with `ConfluencePage`, `ContentType` (page/folder/database), `PaginatedResponse` types. Create `confluence-api-adapter.ts` abstract class with the variant method signatures.

2. **Implement DataCenterApiAdapter** — Implement URL construction (with `os_authType=basic`), response parsing, and child page fetching for Data Center. Simpler of the two adapters (no folders/databases, no N+1). Add unit tests.

3. **Implement CloudApiAdapter** — Implement URL construction, response parsing, and the N+1 child page fetching pattern for Cloud (V2 API for children with separate endpoints for pages/folders/databases, per-child CQL fetch for full metadata). Add unit tests.

4. **Implement ConfluenceApiClient** — Main client class with Bottleneck rate limiter, undici HTTP requests, auth header injection, pagination loop, and 429 retry logic. Delegates to adapter for variant behavior. Add unit tests.

5. **Implement ConfluenceApiClientFactory and registration** — Factory that creates the client with the correct adapter based on config. Register in `TenantRegistry` service initialization. Add unit tests.
