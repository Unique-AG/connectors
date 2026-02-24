# Design: Make API Client the Cloud/DataCenter Boundary

## Problem

The current `ConfluenceApiAdapter` interface mixes two responsibilities: returning configuration/URLs (pure data methods like `buildSearchUrl`, `buildGetPageUrl`, `buildPageWebUrl`) and making HTTP calls (`fetchChildPages` receives an `httpGet` function and orchestrates requests). Additionally, the `ConfluenceApiClient` itself contains a platform-specific check (`instanceType === 'cloud'` for the space type filter in `searchPagesByLabel`), so platform logic leaks into both the adapter and the client.

As flagged in code review: the adapter is a "funny mix of returning config and making calls." The API client itself should be the boundary between Cloud and self-hosted.

## Solution

### Overview

`ConfluenceApiClient` becomes an abstract class retaining all shared infrastructure: the Bottleneck rate limiter, undici HTTP dispatcher, auth token acquisition, rate-limit header logging, and throttle monitoring. It exposes a `protected makeRateLimitedRequest<T>(url: string): Promise<T>` method that subclasses use for authenticated, rate-limited HTTP calls.

Two concrete subclasses implement the platform-specific logic:
- `CloudConfluenceApiClient` — Cloud API endpoints, CQL-based single page lookup, V2 direct-children, collaboration + global spaces
- `DataCenterConfluenceApiClient` — Data Center endpoints with `os_authType=basic`, direct content lookup, V1 child/page, global-only spaces

The `ConfluenceApiAdapter` interface and both adapter classes are deleted. The factory creates the correct subclass. Consumers remain unchanged — they look up `ConfluenceApiClient` (now abstract) via `ServiceRegistry`, which supports `AbstractClass<T>` as a token.

### Architecture

**File structure after refactor:**

```
confluence-api/
├── confluence-api-client.ts          # Abstract base class (shared infra)
├── cloud-api-client.ts               # Cloud-specific implementation
├── data-center-api-client.ts         # DataCenter-specific implementation
├── confluence-api-client.factory.ts  # Creates correct subclass
├── confluence-fetch-paginated.ts     # Unchanged helper
├── types/
│   └── confluence-api.types.ts       # Unchanged
├── __tests__/
│   ├── confluence-api-client.spec.ts        # Shared base behavior
│   ├── cloud-api-client.spec.ts             # Cloud-specific BDD tests
│   ├── data-center-api-client.spec.ts       # DataCenter-specific BDD tests
│   └── confluence-api-client.factory.spec.ts
├── index.ts                          # Updated exports
└── (deleted: confluence-api-adapter.ts, adapters/)
```

**Abstract `ConfluenceApiClient` base class:**
- Constructor: `(config: ConfluenceConfig, serviceRegistry: ServiceRegistry)` — no adapter parameter
- Protected: `makeRateLimitedRequest<T>(url)`, `config`, `baseUrl`, `logger`
- Private: Bottleneck setup, dispatcher, rate-limit logging, throttle monitoring
- Abstract: `searchPagesByLabel()`, `getPageById(pageId)`, `getChildPages(parentId, contentType)`, `buildPageWebUrl(page)`

**Subclasses** implement only the four abstract methods, using `makeRateLimitedRequest` for HTTP calls. Each subclass fully owns its URL construction, response parsing, and child-fetching strategy.

**Factory** switches on `config.instanceType` to instantiate the right subclass, passing `(config, serviceRegistry)`.

**Consumers** (`ConfluencePageScanner`, `ConfluenceContentFetcher`) are unchanged — `serviceRegistry.getService(ConfluenceApiClient)` returns the correct subclass instance transparently.

### Error Handling

No changes. Existing patterns remain:
- `handleErrorStatus` for HTTP errors stays in the base class's `makeRateLimitedRequest`
- Bottleneck error/dropped monitoring stays in the base class
- Consumers continue to catch and handle errors from the public API methods

### Testing Strategy

BDD-style tests in `confluence-api/__tests__/`:

- **`confluence-api-client.spec.ts`** — Shared base behavior: auth header injection, rate limit header logging, Bottleneck throttle monitoring, pagination via `fetchAllPaginated`. Instantiates a concrete subclass to test.
- **`cloud-api-client.spec.ts`** — Cloud-specific behavioral assertions: correct URL construction, CQL with collaboration + global space filters, V2 direct-children child fetching, CQL-based single page lookup with response parsing.
- **`data-center-api-client.spec.ts`** — DataCenter-specific behavioral assertions: correct URL construction with `os_authType=basic`, direct content endpoint for single page lookup, V1 child/page for child pages, global-only space filter.
- **`confluence-api-client.factory.spec.ts`** — Verifies the factory creates the correct subclass type based on `instanceType`.

## Out of Scope

- Changing the `ServiceRegistry` pattern or token types
- Changing the `ConfluenceConfig` schema
- Changing `fetchAllPaginated` — stays as a standalone utility
- Modifying consumers (`ConfluencePageScanner`, `ConfluenceContentFetcher`)
- Performance optimizations (e.g., parallelizing Cloud's N+1 child fetches)
- Adding new API endpoints or features

## Tasks

1. **Refactor `ConfluenceApiClient` into an abstract base class** — Extract shared infrastructure (constructor, rate limiter, dispatcher, `makeRateLimitedRequest`, rate-limit logging, throttle monitoring) into an abstract `ConfluenceApiClient`. Declare `searchPagesByLabel`, `getPageById`, `getChildPages`, and `buildPageWebUrl` as abstract methods.

2. **Create `DataCenterConfluenceApiClient`** — Implement abstract methods using Data Center API endpoints (`/rest/api/content/...` with `os_authType=basic`), direct content endpoint for single page lookup, V1 `child/page` for child pages, and global-only space filter.

3. **Create `CloudConfluenceApiClient`** — Implement abstract methods using Cloud API endpoints (`/wiki/rest/api/...` and `/wiki/api/v2/...`), CQL-based single page lookup with response parsing, V2 `direct-children` for child pages, and cloud space type filter (global + collaboration).

4. **Update `ConfluenceApiClientFactory`** — Change the factory to instantiate `CloudConfluenceApiClient` or `DataCenterConfluenceApiClient` based on `config.instanceType`, removing adapter creation.

5. **Delete adapter layer** — Remove `confluence-api-adapter.ts`, `adapters/cloud-api.adapter.ts`, `adapters/data-center-api.adapter.ts`, their spec files, and update `index.ts` exports.

6. **Write tests** — Create BDD-style specs in `__tests__/`: shared base behavior spec, Cloud client spec, DataCenter client spec, and update the factory spec.
