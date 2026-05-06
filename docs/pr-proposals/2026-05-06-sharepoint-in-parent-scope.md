# PR Proposal

## Ticket

UN-20365

## Title

feat(sharepoint-connector): support `in_parent:` scope auto-creation [UN-20365]

## Description

- Accept `in_parent:scope_<id>` as a SharePoint List `scopeId` value; connector finds-or-creates a child scope under the given parent and uses it as the site root, mirroring v1's auto-create UX without requiring Champions to pre-create a scope per site.
- Resolution: try `getScopeByExternalId('spc:{siteId}/site')` and move on parent-mismatch; otherwise scan one `listChildrenScopes(parent)` call for both legacy-externalId reuse and the name-match abort cases (unclaimed / foreign / ambiguous); finally create + claim, rolling back the create if claiming fails. Existing `ScopeExternalIdMigrationService` (running inside `initializeRootScope`) normalizes any legacy externalId afterward.
- Unify site deletion: `auto` rows additionally delete the auto-created root after `resetRootScope`; `fixed` rows behave as today. The parent's externalId is never written.
- Keep dedup-by-scopeId for `fixed` rows (skipping `auto`, since multiple sites legitimately share a parent) and add dedup-by-siteId so the same SharePoint site cannot be configured to two different roots.
- No helm / Terraform / RBAC changes; docs updated for the new prefix.
