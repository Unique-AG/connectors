# Design: SharePoint Connector v2 — `in_parent:` scope auto-creation

**Ticket:** UN-20365

## Problem

SharePoint Connector v2 currently requires every SP-List row to carry an existing Scope ID. A client has rejected this: their Champions cannot pre-create one scope per ingestion request. The v1 connector auto-created scopes and is what they have running today; the ask is to bring the same convenience to v2.

Per comment on UN-20365, the agreed shape is to keep the single "Scope ID" column and overload its value: a plain `scope_<id>` keeps today's behaviour, while a `in_parent:<parent-scope-id>` value tells the connector to find-or-create a child scope under the given parent. Customers still write one row per site, but they no longer have to materialise scopes manually.

## Solution

### Overview

The `scopeId` cell on a SharePoint List row becomes a two-variant value, parsed into a discriminated union at config-load time:

- `fixed` — `scope_<id>` — today's behaviour: this scope is the site root; connector claims it with `spc:{siteId}/site`.
- `auto` — `in_parent:scope_<id>` — connector finds-or-creates a child scope under the given parent, uses it as the site root. The parent stays user-managed and is **never** claimed with `externalId`.

A new `ScopeManagementService.resolveRootScopeId(siteConfig)` method runs at the top of `synchronizeSingleSite` and produces a concrete root scope ID for both variants. From that point on, the existing pipeline (`initializeRootScope`, child-scope creation, stale-marking, content sync) is unchanged.

Site deletion (`syncStatus: 'deleted'`) is unified: same reset-then-optionally-delete path for both variants, with the `auto` branch adding a single `deleteScope(rootId)` call after `resetRootScope`.

### Architecture

**Schema (`config/sharepoint.schema.ts`).** `SiteConfigSchema.scopeId` becomes a Zod transform producing:

```ts
type ScopeIdConfig =
  | { type: "fixed"; scopeId: string }
  | { type: "auto"; parentScopeId: string };
```

Both branches validate against `^scope_[a-z0-9]+$`. The `in_parent:` prefix is exact; whitespace is trimmed but not otherwise tolerated.

**Resolution (`ScopeManagementService.resolveRootScopeId`).**

For `fixed`: returns `scopeId` directly.

For `auto`, in order:

1. **`getScopeByExternalId('spc:{siteId}/site')`** — global lookup. If found and `parentId === parentScopeId`, reuse. If found and parent mismatches, `updateScopeParent(scopeId, parentScopeId)` and reuse (the move-on-mismatch signal that configuration changed).
2. **`listChildrenScopes(parentScopeId)`** — single call, scanned for:
   - **Any externalId pointing at this site.** Match either the new format (`spc:{siteId}/site`) or the legacy format (`spc:site:{siteId}`); reuse. `ScopeExternalIdMigrationService.migrateIfNeeded(siteId)` already runs inside `initializeRootScope` later and will normalize legacy forms there — no explicit migration probe is needed in resolution.
   - **Otherwise, name match against `context.siteName`** (the URL-safe slug from the SharePoint webUrl, the same value the existing path code uses):
     - 0 matches → step 3.
     - 1 match, `externalId == null` → abort: refusing to claim an unclaimed scope.
     - 1 match, foreign `spc:` externalId → abort: site folder owned by a different site.
     - > 1 matches → abort: ambiguous.
3. **Create + claim:** compute parent path (walk up from parent scope), call `createScopesBasedOnPaths([parentPath/siteName], { inheritAccess: false })`, then `updateScopeExternalId(newId, 'spc:{siteId}/site')`. **If the claim step fails, immediately `deleteScope(newId, { recursive: true })` and rethrow** — never leave an unclaimed scope behind.

**Sync flow (`SharepointSynchronizationService`).**

- Dedup runs in two passes:
  - **`deduplicateByScopeId`** is kept for `fixed` rows; `auto` rows are skipped (multiple sites legitimately share the same parent).
  - **`deduplicateBySiteId`** is added (the codebase has no dedup-by-siteId today): two rows for the same SharePoint site are a configuration error regardless of variant; keep the first, log the duplicate.
- `synchronizeSingleSite` calls `resolveRootScopeId(siteConfig, siteName)` after `siteName` is fetched (existing `getSiteInfo` call at `sharepoint-synchronization.service.ts:241`) and before `initializeRootScope`. The resolved ID is threaded through `SharepointSyncContext.rootScopeId`, replacing direct reads of `siteConfig.scopeId` downstream.
- No new Graph call is needed — the existing `context.siteName` (URL-safe slug from `extractSiteNameFromWebUrl`) is the value used for the name match and creation path. This matches what beta.5 used for path building, so existing site folders line up.

**Site deletion.** `processSingleSiteDeletion` is unified across variants:

1. Resolve root scope in lookup-only mode (no create, no move). If not found → idempotent return.
2. `uniqueFilesService.deleteFilesBySiteId(siteId)`.
3. `resetRootScope(rootId)`.
4. If `siteConfig.scopeId.type === 'auto'`: `deleteScope(rootId)`.

The parent's `externalId` is never written.

### Direction transitions

- `fixed → in_parent:` — step 1 finds the claimed scope, moves it under the new parent.
- `in_parent: → fixed` — `initializeRootScope` sees the new fixed scope is unclaimed, the existing `RootScopeMigrationService.migrateIfNeeded` bulk-moves children from the auto-created root and deletes it.
- `in_parent:<X> → in_parent:<Y>` — step 1 finds the claimed scope, moves it under Y.

### Error Handling

A typed `RootScopeResolutionError` (or discriminated subclasses) is raised for:

- `unclaimed_name_match` — name collision with an unclaimed scope under the parent.
- `foreign_name_match` — name collision with a scope claimed by a different site.
- `ambiguous_name_match` — multiple children share the name.
- `claim_failed` — create succeeded but the externalId update failed; rollback delete is attempted and any rollback failure logged before the original error is rethrown.

These are configuration-fix errors. A single failing site does not poison other sites' syncs (existing per-site try/catch in `synchronizeAllSites` covers that).

### Testing Strategy

Behavioural tests, hitting the same in-memory test setup the existing services use:

- `scope-management.service.spec.ts` — `resolveRootScopeId`:
  - `fixed` → returns input verbatim.
  - `auto` + no existing scope → creates + claims.
  - `auto` + existing scope claimed (new format) under correct parent → reuses, no writes.
  - `auto` + existing scope claimed (new format) under wrong parent → `updateScopeParent` called.
  - `auto` + child of parent has legacy `spc:site:{siteId}` externalId → reuses; relies on `initializeRootScope`'s migration to normalize the format on the next step.
  - `auto` + unclaimed name match → throws.
  - `auto` + foreign name match → throws.
  - `auto` + ambiguous name match → throws.
  - `auto` + create succeeds, claim fails → rollback `deleteScope` invoked, throws.

- `sharepoint-synchronization.service.spec.ts`:
  - Existing `deduplicateByScopeId` test still passes; `auto` rows with identical cell values are not deduped by it (covered by the new siteId pass instead).
  - New `deduplicateBySiteId` test — two rows with the same siteId (any variant mix) collapse to the first.
  - `auto` deletion branch invokes `deleteScope` after `resetRootScope`; `fixed` deletion branch does not.

- `sharepoint.schema.spec.ts` — schema parsing of `scope_xxx`, `in_parent:scope_xxx`, malformed inputs.

### Surrounding Artifacts Impact

- **Docs:** Update `services/sharepoint-connector/README.md` and any tenant-config examples to describe the `in_parent:` prefix and the abort conditions. Confluence "SharePoint Connector v2 Ingestion Request Process" page also needs updating (separate Action item on the ticket; not required for the PR but called out for traceability).
- **Helm charts:** none — no new config values, no new env, no new RBAC.
- **Terraform modules:** none — purely application logic.
- **Other deployment surface:** none — no migration scripts; existing legacy externalId migration covers already-deployed scopes via `ScopeExternalIdMigrationService`.

## Out of Scope

- Empty-cell auto-create. Every site gets its own row; `in_parent:` is the explicit opt-in.
- Configurable site-folder name. Always uses the SharePoint site display name.
- Relocating site folders that were created outside the configured parent and aren't the current site's claimed root — only the claim-by-externalId-then-`updateScopeParent` path is supported.
- Auto-recovery for an unclaimed name collision — operator resolves manually.
- v1 connector changes — out of scope; v1 already auto-creates.

## Tasks

1. **Update `SiteConfigSchema.scopeId` to a discriminated union** — Replace the free-form string with a Zod transform that produces `{ type: 'fixed'; scopeId } | { type: 'auto'; parentScopeId }`. Validate `scope_<alphanumeric>` shape on both branches. Add schema-level tests.

2. **Thread the resolved root scope ID through `SharepointSyncContext`** — Add `rootScopeId: string` to `sharepoint-sync-context.interface.ts` and replace all downstream reads of `siteConfig.scopeId` with `context.rootScopeId`. The discriminated union is only inspected in resolution and deletion code.

3. **Fetch SharePoint site display name and put it on the sync context** — Either extend the existing site-info call in `SitesConfigurationService` / sync setup or add a small Graph helper. Cache once per site per sync run.

4. **Implement `ScopeManagementService.resolveRootScopeId`** — Three steps from the design (global externalId lookup with parent-mismatch move, single `listChildrenScopes` call covering both legacy-externalId match and name-match-with-abort cases, create+claim with rollback). Add typed `RootScopeResolutionError` cases.

5. **Wire `resolveRootScopeId` into `synchronizeSingleSite`** — Call it after `siteName` is fetched, before `initializeRootScope`. Pass the resolved ID forward via `SharepointSyncContext.rootScopeId`. Skip `auto` rows in the existing `deduplicateByScopeId`; add a new `deduplicateBySiteId` pass that runs for both variants.

6. **Unify deletion in `processSingleSiteDeletion`** — Resolve the root in lookup-only mode (no create/move); call `deleteFilesBySiteId` + `resetRootScope` for both variants; add `deleteScope(rootId)` only for `auto`. Idempotent if the scope is already gone.

7. **Behavioural tests** — `scope-management.service.spec.ts`, `sharepoint-synchronization.service.spec.ts`, schema spec, per the Testing Strategy section.

8. **Docs** — Update `services/sharepoint-connector/README.md` and tenant-config examples to document the `in_parent:` prefix, the abort conditions, and the deletion semantics for `auto` rows.
