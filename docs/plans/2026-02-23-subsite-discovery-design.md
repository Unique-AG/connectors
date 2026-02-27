# Design: Recursive Subsite Discovery and Sync

**Ticket:** UN-17398

## Problem

The SharePoint connector only syncs content from explicitly configured top-level sites. Some clients use SharePoint subsites (a deprecated but still functional feature) to organize content. Subsites and their content — including drives and ASPX pages — are invisible to the connector, meaning documents stored in subsites are never synced.

Subsites can be arbitrarily nested (subsites within subsites). The connector must recursively discover and scan the entire subsite tree for each configured site.

## Solution

### Overview

Introduce a per-site **`subsitesScan`** option (`'enabled' | 'disabled'`, default `'disabled'`) that controls whether subsite discovery runs. When enabled, introduce a **subsite discovery phase** before item fetching: recursively enumerate all subsites via the Microsoft Graph API (`GET /sites/{siteId}/sites`), building a tree that preserves the subsite hierarchy. Each discovered subsite carries its relative path from the root site (e.g., `B`, `B/D`, `C`). Then run the existing item-fetching logic (`getAllFilesForSite` + `getAspxPagesForSite`) for the parent site **and** each discovered subsite. All items and directories are merged into a single collection.

The URL-based scope path extraction (`getRelativeUniquePathFromUrl`) already strips only the first two URL segments (`/sites/{SiteName}`). For subsite items, the subsite name(s) naturally remain in the path, producing correct hierarchical scope paths without any changes to the path logic.

For example, given site A with subsites B and C, where B has subsite D:

```
A (root site)
├── B (subsite, relativePath: "B")
│   └── D (subsite, relativePath: "B/D")
└── C (subsite, relativePath: "C")
```

The resulting scope paths preserve this hierarchy:
- `/Root/Documents/...` — items from site A
- `/Root/B/Documents/...` — items from subsite B
- `/Root/B/D/Documents/...` — items from subsite D
- `/Root/C/Documents/...` — items from subsite C

The sync flow changes from:

**Before:** site → fetch items → create scopes → sync

**After (subsitesScan: enabled):** site → discover subsites → fetch items for site + each subsite → merge → create scopes → sync

**After (subsitesScan: disabled):** unchanged — same as before

### Architecture

#### New Component: `SubsiteDiscoveryService`

An injectable service responsible for recursively discovering all subsites of a given site. It calls `GraphApiService.getSubsites(siteId)` and recurses into each result, tracking the relative path at each level.

```
interface DiscoveredSubsite {
  siteId: Smeared;
  name: string;
  relativePath: string;  // e.g., "B", "B/D", "C" — path from root site
}

SubsiteDiscoveryService
  └── discoverAllSubsites(rootSiteId: Smeared): Promise<DiscoveredSubsite[]>
```

Returns all descendant subsites with their relative paths preserved. The parent site itself is not included — it's already handled by the existing flow. The recursive discovery builds the `relativePath` by appending each subsite's name to its parent's path (e.g., subsite D under B gets `relativePath: "B/D"`).

#### New Method: `GraphApiService.getSubsites(siteId)`

A paginated Graph API call to `GET /sites/{siteId}/sites`, following the same pattern as `getDrivesForSite` and `getSiteLists`. Works with existing `Sites.Selected` permission when the parent site has read access.

#### Modified Orchestration

A new wrapper method (e.g., `getAllItemsIncludingSubsites`) that:

1. Calls `SubsiteDiscoveryService.discoverAllSubsites(siteId)` to get all subsites with their relative paths
2. Calls the existing `getAllSiteItems(siteId, ...)` for the parent site
3. Calls `getAllSiteItems(subsiteId, ...)` for each discovered subsite
4. Merges all items and directories together — each subsite's items naturally carry the correct hierarchical paths in their SharePoint URLs

This replaces the direct `getAllSiteItems` call in `syncSite`. The existing `getAllSiteItems` remains untouched — it still handles a single site.

#### Path Handling (no changes needed)

The current `getRelativeUniquePathFromUrl` strips `/sites/{SiteName}` (2 segments). For subsite items, the URL naturally includes the subsite path:

| Item location | SharePoint URL path | After stripping 2 segments |
|---|---|---|
| Parent site | `/sites/MySite/Documents/file.docx` | `/Documents/file.docx` |
| Subsite A | `/sites/MySite/SubA/Documents/file.docx` | `/SubA/Documents/file.docx` |
| Nested Sub B | `/sites/MySite/SubA/SubB/Documents/file.docx` | `/SubA/SubB/Documents/file.docx` |

The scope tree automatically mirrors the subsite hierarchy.

#### Orphan Scope Cleanup

The `deleteOrphanedScopes` method searches by the parent site's `siteId` prefix. Subsite scopes have external IDs containing their own `siteId`. The cleanup step must be extended to also cover discovered subsite IDs so orphaned subsite scopes are properly cleaned up.

### Error Handling

If any subsite discovery or item-fetching fails, the entire parent site sync fails. Since discovery happens first (before any content processing), a discovery failure fails early and cleanly. An item-fetching failure for any subsite propagates up and fails the parent site's `syncSite` call.

### Testing Strategy

- **`SubsiteDiscoveryService`** — unit tests covering: no subsites found, single-level subsites, deeply nested subsites, and error propagation.
- **`GraphApiService.getSubsites`** — unit test for the paginated Graph API call, same pattern as existing `getSiteLists` / `getDrivesForSite` tests.
- **Modified orchestration** — update existing `SharepointSynchronizationService` tests to verify subsite items are included in sync and that a subsite failure fails the parent site.
- **Path handling** — add a test case with a subsite URL to `sharepoint.util` tests to document the behavior explicitly.

## Out of Scope

- **Global-level subsites toggle** — the option is per-site only, not global.
- **Recursion depth limits** — no cap on nesting depth.
- **Per-subsite sync column** — subsites inherit the parent's `syncColumnName`.
- **Subsite-level permissions config** — permissions use the same mode as the parent site config.
- **Subsite deletion tracking** — removed subsites become orphaned and get cleaned up via existing mechanisms.

## Tasks

1. **Add `subsitesScan` option to `SiteConfig`** — Add a `subsitesScan: 'enabled' | 'disabled'` field (default `'disabled'`) to `SiteConfigSchema` in `sharepoint.schema.ts`. Update the Helm values schema and example config files accordingly.

2. **Add `getSubsites` method to `GraphApiService`** — A paginated Graph API call to `GET /sites/{siteId}/sites` returning `Site[]`. Follows the same pattern as `getDrivesForSite` and `getSiteLists`. Include a unit test.

3. **Create `SubsiteDiscoveryService`** — An injectable service with a `discoverAllSubsites(rootSiteId)` method that recursively calls `getSubsites`, building the `relativePath` for each subsite by appending its name to its parent's path (preserving the full hierarchy, e.g., `B/D` for subsite D under B). Include unit tests covering no subsites, single-level, nested, and error propagation.

4. **Add wrapper method for fetching items across site and subsites** — A new method (e.g., `getAllItemsIncludingSubsites`) that calls `SubsiteDiscoveryService.discoverAllSubsites` when `subsitesScan` is `'enabled'`, then runs the existing `getAllSiteItems` for the parent site and each discovered subsite (preserving hierarchy via relative paths), merging all items and directories. When `subsitesScan` is `'disabled'`, falls through to the existing `getAllSiteItems` call unchanged. Wire this into the sync orchestration in `SharepointSynchronizationService`. Include unit tests for both enabled and disabled paths.

5. **Extend orphan scope cleanup to cover subsites** — Modify `deleteOrphanedScopes` (or its caller) to also clean up orphaned scopes for discovered subsite IDs, not just the parent site's ID. Include a unit test for subsite orphan cleanup.

6. **Update permissions documentation** — Update `docs/technical/permissions.md` and `docs/technical/architecture.md` to document the new `/sites/{siteId}/sites` endpoint usage and the `subsitesScan` config option.
