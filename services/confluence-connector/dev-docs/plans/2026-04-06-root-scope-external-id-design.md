# Design: Root scope external ID and ownership validation

**Ticket:** UN-18352

## Problem

The Confluence connector v2 does not set an external identifier on its root scope. There is no protection against misconfiguration where the same Confluence instance is connected to multiple Unique orgs, or the same root scope is pointed at a different Confluence instance. The SharePoint connector already solves this with `spc:site:<siteId>` on the root scope.

## Solution

### Overview

Add instance identifier resolution to the `ConfluenceApiClient` abstract class and ownership validation to `ScopeManagementService.initialize()`. On the first sync cycle (when the root scope has no `externalId`), the connector claims the root scope by setting `externalId` to `confc:cloud:<instanceId>` (Cloud) or `confc:dc:<instanceId>` (Data Center). On subsequent syncs, it validates that the root scope's `externalId` matches the current instance. A mismatch is a fatal error.

The Confluence connector supports both Cloud and Data Center instances, which have different identifier strategies:
- **Cloud**: `cloudId` from tenant config. Always available, globally unique UUID per Atlassian Cloud site.
- **Data Center**: `id` from `GET /rest/applinks/1.0/manifest`. A stable instance UUID assigned at Confluence installation time. Persists across URL changes and upgrades. Requires no authentication or admin permissions.

### Architecture

New abstract method on `ConfluenceApiClient`:

```
abstract resolveInstanceIdentifier(): Promise<InstanceIdentifier>
```

Where `InstanceIdentifier = { type: 'cloud' | 'data-center'; id: string }`.

- `CloudConfluenceApiClient`: returns `{ type: 'cloud', id: config.cloudId }` from config.
- `DataCenterConfluenceApiClient`: calls `GET ${baseUrl}/rest/applinks/1.0/manifest` via `RateLimitedHttpClient` (no auth headers), parses the `id` field from the JSON response.

Updated flow in `ScopeManagementService.initialize()`:

```
1. Get user ID, grant access (existing)
2. Fetch root scope by ID (existing)
3. apiClient.resolveInstanceIdentifier()              <- NEW
4. Build expected externalId:
   "confc:cloud:<instanceId>" or "confc:dc:<instanceId>"
5. Validate ownership:                                 <- NEW
   - externalId exists AND differs -> fatal error
   - externalId is null -> claim the scope (set externalId)
   - externalId matches -> proceed
6. Build root path (existing)
7. Return { rootScopePath, isInitialSync }             <- CHANGED
```

The `ScopeManagementService` constructor gains two new parameters: `confluenceConfig` (for building the external ID) and the `ConfluenceApiClient` instance (for resolving the instance identifier). The instance identifier is cached after first resolution.

### Error Handling

- **Ownership mismatch**: Fatal `assert.ok()` failure. Stops the sync cycle entirely. Same pattern as SharePoint.
- **Claim failure**: Non-fatal warning log. Could happen on a race condition (defensively handled, though `isScanning` flag prevents concurrent syncs).
- **DC manifest fetch failure**: Propagates up and fails the sync cycle. Retries on next cron tick. Cached after first success so subsequent syncs skip the HTTP call.
- **DC manifest missing `id` field**: Throws a descriptive error.

### Testing Strategy

Use existing test patterns from `scope-management.service.spec.ts`.

Instance identifier resolution tests (per API client):
- Cloud: returns identifier from config, no HTTP call
- DC: mock HTTP response, verify correct URL and parsing
- DC: error on non-2xx response
- DC: error on missing/invalid `id` in response

Ownership validation tests (in scope management):
- No externalId on root scope: claims it (initial sync)
- Matching externalId: proceeds normally (not initial sync)
- Different externalId: throws fatal error

`buildRootScopeExternalId` is a pure function, tested directly.

## Out of Scope

- **Root scope migration** when `scopeId` changes in config (deferred to a follow-up ticket, following SharePoint's `RootScopeMigrationService` pattern).
- **Duplicate instance warning** across orgs. The ticket mentions logging a warning if the same Confluence instance identifier is detected across different Unique orgs. This requires cross-org visibility via `getScopeByExternalId` which may match scopes from any org. We will defer this unless the API already supports it.
- **Conflict with PR #421** (UN-18296 cleanup removed spaces). That PR changes space-level external IDs. Our work is on the root scope level with a different format. Both modify `scope-management.service.ts`. We will resolve merge conflicts when both PRs land.

## Tasks

1. **Add `resolveInstanceIdentifier()` to the API client hierarchy** - Add an abstract method to `ConfluenceApiClient`. Cloud implementation returns `cloudId` from config. DC implementation calls `GET /rest/applinks/1.0/manifest` via `RateLimitedHttpClient` with empty auth headers, parses and validates the `id` field. Add unit tests for both clients.

2. **Add `buildRootScopeExternalId()` helper** - Pure function in `ingestion.constants.ts` that takes instance type and ID, returns `confc:cloud:<id>` or `confc:dc:<id>`. Unit test it.

3. **Add ownership validation and claiming to `ScopeManagementService.initialize()`** - After fetching the root scope, resolve the instance identifier, validate ownership, claim on initial sync. Change return type to `{ rootScopePath, isInitialSync }`. Cache the resolved instance identifier. Update constructor to accept `ConfluenceConfig` and `ConfluenceApiClient`. Add unit tests for all three ownership scenarios.

4. **Wire up new dependencies in `TenantRegistry`** - Pass `config.confluence` and the `apiClient` instance to `ScopeManagementService`. Update `ConfluenceSynchronizationService` to destructure the new return type from `initialize()`.

5. **Update existing tests** - Update `scope-management.service.spec.ts` mock setup for new constructor params. Update `confluence-synchronization.service.spec.ts` mock for new `initialize()` return type.
