# PR Proposal

## Ticket
UN-17215

## Title
refactor(sharepoint-connector): route scope operations through node-ingestion client

## Description
- Re-route `paginatedScope`, `generateScopesBasedOnPaths`, `updateScope`, `createScopeAccesses`, `deleteScopeAccesses`, and `deleteFolder` in `UniqueScopesService` from `SCOPE_MANAGEMENT_CLIENT` to `INGESTION_CLIENT`, matching where `bulkMove` already lives.
- Drop the now-unused scope-management client injection from `UniqueScopesService`; `SCOPE_MANAGEMENT_CLIENT` stays for `UniqueUsersService` and `UniqueGroupsService`.
- Update `unique-scopes.service.spec.ts` to assert against the ingestion client mock; GraphQL documents and variable shapes are unchanged.
- Relies on node-ingestion's server-side backwards compatibility for scope operations — no helm/terraform/config changes.
- Recommend a staging sync run exercising create / update / delete / list / access paths as the end-to-end check before merge.
