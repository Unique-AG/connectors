# Design: Make SharePoint Site-Sync Default Values Configurable

**Ticket:** UN-20464

## Problem

The SharePoint connector defines 10 per-site sync settings (`siteId`, `syncColumnName`, `ingestionMode`, `scopeId`, `maxFilesToIngest`, `storeInternally`, `syncStatus`, `syncMode`, `permissionsInheritanceMode`, `subsitesScan`). Five fields have schema-level defaults; four are required (`siteId`, `ingestionMode`, `scopeId`, `syncMode`); one is optional with no default (`maxFilesToIngest`).

Tenants operating multiple sites with similar sync settings must repeat the same values on every site row — whether in YAML (`config_file` source) or in the SharePoint configuration list (`sharepoint_list` source). Customer SIX has asked to set those values once at deployment level (via Helm) and only override per-site when needed.

## Solution

### Overview

Add a new `sharepoint.siteDefaults` block in the tenant config (rendered by Helm). It accepts the same fields as a site minus `siteId`; every field is optional and may be omitted. At config-load time, the block is parsed by Zod, where today's schema-level defaults fill in any field the deployment didn't override — producing a fully-populated defaults object.

When sites are loaded (from either source mode), each site row is parsed against a **partial** site schema with no defaults applied. The connector then merges per-site values with `siteDefaults` — per-site wins if "set," meaning a value that is neither `undefined` nor an empty/whitespace string. The merged result is validated against the **strict** `SiteConfigSchema`, which enforces required-field presence and type constraints.

This is a single merge step with two effective layers (per-site over deployment defaults). The schema-level defaults remain in place as the fallback baked into `siteDefaults` parsing — so existing tenant configs with no `siteDefaults` block continue to behave as they do today.

Scope: all per-site fields except `siteId` are eligible for deployment defaults. Both source modes (`config_file` and `sharepoint_list`) flow through the same merge logic.

### Architecture

**Schema changes** (`src/config/sharepoint.schema.ts`):

- Extract `SiteDefaultsSchema`: same fields as `SiteConfigSchema`, with `siteId` removed and the four required fields (`ingestionMode`, `scopeId`, `syncMode`, plus the always-required `siteId` which is excluded entirely) made optional. Schema-level `.default()` / `.prefault()` calls on the 5 already-defaulted fields are preserved here so they apply when the tenant config omits them. Use `.default({})` on the wrapper so the entire block is optional.
- Add `PartialSiteConfigSchema` for parsing per-site rows: every field optional, every default stripped. `siteId` retains its strict format check (UUID or compound) only when present — a row with no `siteId` parses to `undefined` here. Validation happens after merge.
- `SharepointConfigSchema` gains a `siteDefaults: SiteDefaultsSchema` field.
- `SiteConfigSchema` itself is unchanged and stays the post-merge validation target.

**Merger** (new file: `src/config/site-config-merger.ts`):

A pure function `mergeSiteWithDefaults(partialSite, siteDefaults, rowIdentifier): SiteConfig`:

1. For each field in the partial site, take the per-site value if "set" (non-undefined, non-empty/whitespace string), else the value from `siteDefaults`.
2. Pass the merged object through `SiteConfigSchema.parse()` for final validation.
3. Throw on missing required fields with a descriptive message identifying the row and which fields are missing both per-site and in defaults.

**Sites loading flow** (`src/microsoft-apis/graph/sites-configuration.service.ts`):

- `loadSitesConfiguration()` reads `sharepoint.siteDefaults` from config alongside `sitesSource`.
- For `config_file`: the existing `sites` array is parsed as `PartialSiteConfigSchema[]`. Each partial is then run through the merger.
- For `sharepoint_list`: `transformListItemToSiteConfig` returns a partial via `PartialSiteConfigSchema.parse`. The merger is called for each list row.
- Single code path for the merge regardless of source.

### Error Handling

- **Missing required field after merge** — Merger throws with `Site row N ('siteId': ...): required field 'X' is not set per-site and has no deployment default`. Wrapped by the existing row-level catch so the row index/identifier surfaces in logs.
- **Invalid value at any layer** — Zod's existing parse errors propagate (e.g., a list cell with `ingestionMode: "weird"` still fails fast on the post-merge `SiteConfigSchema.parse`). Same fail-fast semantics as today.
- **Invalid `siteDefaults` block at startup** — Zod parse fails at NestJS config load. Service won't boot. Same loud-failure semantics as today's malformed tenant config.
- **Empty SharePoint list** — Still returns an empty array. Defaults don't conjure sites out of nowhere.
- **`siteId` with cross-field constraints** — `siteId` is excluded from defaults, so cross-site context is never an issue.

Failure mode is preserved: a single unresolvable site aborts the entire `loadSitesConfiguration` call. Switching to per-row resilience is out of scope.

### Testing Strategy

Behavioral tests using the existing Vitest setup, three surfaces:

1. **Schema tests** (`sharepoint.config.spec.ts`):
   - `SiteDefaultsSchema`: accepts `{}`, accepts partial, applies schema defaults to omitted defaultable fields, leaves required-defaultable fields undefined when omitted, rejects invalid values.
   - `PartialSiteConfigSchema`: accepts any subset, validates `siteId` format only when present.
   - Wrapper default — `siteDefaults` absent in tenant config parses to a populated-with-schema-defaults object.

2. **Merger tests** (new `site-config-merger.spec.ts`):
   - Per-site value wins when set.
   - Empty/whitespace string in per-site falls through.
   - `undefined` in per-site falls through.
   - `0` and `false`-ish enum values are taken as set (sanity).
   - Required field missing in both → descriptive throw including row identifier.
   - All required fields set per-site, defaults empty → succeeds (back-compat).
   - Result shape matches `SiteConfig` (post-`.transform` `siteId` is `Smeared`, etc.).

3. **Service tests** (`sites-configuration.service.spec.ts`):
   - `config_file` mode merges defaults into partial rows.
   - `sharepoint_list` mode merges defaults into rows fetched from Graph.
   - No `siteDefaults` configured ≡ today's behavior (regression).
   - One row missing both per-site and default required field aborts the whole load (regression).

### Surrounding Artifacts Impact

- **Docs:**
  - `services/sharepoint-connector/default-tenant-config.example-config-file.yaml` — add commented `siteDefaults:` block; trim a couple of fields from one of the example sites to demonstrate fall-through.
  - `services/sharepoint-connector/default-tenant-config.example-sharepoint-list.yaml` — add the same `siteDefaults:` block; soften the "Required SharePoint list columns" comment.
  - Helm chart `README.md` is regenerated from `values.yaml` via `pnpm helm-docs:sharepoint`; no manual edit.

- **Helm charts:**
  - `services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/values.yaml` — add empty `connectorConfig.sharepoint.siteDefaults: {}` with commented examples. Empty default keeps existing deployments behaving identically.
  - `templates/tenant-config.yaml` — render `siteDefaults` from values; expected to flow through the existing generic block, verify against snapshot.
  - `tests/regressions._test.yaml` — add a helm-unittest case asserting that a populated `siteDefaults` plus a stripped-down site row render correctly into `data["default-tenant-config.yaml"]`.
  - No new env vars, secrets, RBAC, probes, or resource limits.

- **Terraform modules:** none — application config flowing through Helm; no IAM, networking, queues, buckets, or KMS keys involved.

- **Other deployment surface:** none — no CI/CD, GitHub Actions, env-var matrices, feature flags, or migration scripts touched. Change is backward-compatible: tenants without `siteDefaults` keep working unchanged.

## Out of Scope

- **Per-row resilience.** Today, one invalid site aborts the whole `loadSitesConfiguration`. We preserve that behavior. Switching to "skip bad rows, log and continue" is a separate ticket.
- **Backfilling old behavior.** No data migration. Existing tenants opt in by adding the block.
- **New default-eligible fields.** Only the 9 existing per-site fields (everything except `siteId`).
- **Per-site overrides for non-site fields.** `processing.*`, `unique.*`, and `sharepoint.graphApiRateLimitPerMinuteThousands` stay deployment-only.
- **Helm chart introspection helpers.** No template-side validation of `siteDefaults` shape; validation lives in the application's Zod schema.
- **UI / dashboard** for managing defaults. The SharePoint list itself is the operator UI.
- **Cross-site composition** (groups, profiles, inheritance). One flat defaults block, applied uniformly.

## Tasks

1. **Refactor `sharepoint.schema.ts` to add defaults and partial schemas** — Extract `SiteDefaultsSchema` (drops `siteId`, makes required fields optional, retains schema-level defaults on the 5 already-defaulted fields, defaults the wrapper to `{}`). Add `PartialSiteConfigSchema` for parsing per-site rows with all fields optional and no defaults. Add `siteDefaults` to `SharepointConfigSchema`. Update exported `SharepointConfig` type.

2. **Implement the site config merger** — New file `src/config/site-config-merger.ts` exporting `mergeSiteWithDefaults(partialSite, siteDefaults, rowIdentifier)`. Applies the "set means non-undefined and non-empty/whitespace string" rule, validates merged result via `SiteConfigSchema.parse`, throws with row identifier and missing-field details on failure.

3. **Wire the merger into `SitesConfigurationService`** — Read `siteDefaults` from config alongside `sitesSource`. For `config_file`, parse `sites:` as `PartialSiteConfigSchema[]` and merge each. For `sharepoint_list`, change `transformListItemToSiteConfig` to return a partial via `PartialSiteConfigSchema.parse`, then merge. Keep current fail-fast semantics on the wrapping error path.

4. **Update example tenant config YAMLs** — Add commented `siteDefaults:` block to both `default-tenant-config.example-config-file.yaml` and `.example-sharepoint-list.yaml`. In the config-file example, omit a couple of fields from one site row to illustrate fall-through. In the sharepoint-list example, soften the "Required SharePoint list columns" comment.

5. **Add `siteDefaults` to Helm values and template** — Empty `connectorConfig.sharepoint.siteDefaults: {}` in `values.yaml` with commented field examples. Verify `templates/tenant-config.yaml` renders the new key via existing pass-through; add explicit handling only if the template special-cases the sharepoint block.

6. **Regenerate Helm chart README** — Run `pnpm helm-docs:sharepoint` so `README.md` picks up the new `connectorConfig.sharepoint.siteDefaults` entry from the updated `values.yaml`.

7. **Add helm-unittest case for `siteDefaults` rendering** — Extend `tests/regressions._test.yaml` (or a new sibling file) with a test that sets `connectorConfig.sharepoint.siteDefaults` to a representative block plus a stripped-down site row, and asserts that `data["default-tenant-config.yaml"]` contains the expected `siteDefaults:` lines and the partial site row.

8. **Schema tests** — Extend `sharepoint.config.spec.ts` with cases covering `SiteDefaultsSchema`, `PartialSiteConfigSchema`, and the wrapper default.

9. **Merger tests** — New `site-config-merger.spec.ts` covering: per-site wins when set; empty/whitespace falls through; undefined falls through; merged result satisfies strict schema; missing required field after merge throws with row identifier; transformed types (e.g. `Smeared` `siteId`) survive the round trip.

10. **Service tests** — Extend `sites-configuration.service.spec.ts` with: `config_file` mode merges defaults; `sharepoint_list` mode merges defaults; no `siteDefaults` configured ≡ today's behavior (regression); a row missing both per-site and default for a required field aborts the whole load (regression).
