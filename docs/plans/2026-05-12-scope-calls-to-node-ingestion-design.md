# Design: Move scope-management calls in sharepoint-connector to node-ingestion

**Ticket:** UN-17215

## Problem

The SharePoint connector's `UniqueScopesService` currently splits scope-related GraphQL traffic across two clients:

- `bulkMove` already uses `INGESTION_CLIENT` (node-ingestion).
- Everything else — `paginatedScope`, `generateScopesBasedOnPaths`, `updateScope`, `createScopeAccesses`, `deleteScopeAccesses`, `deleteFolder` — still goes through `SCOPE_MANAGEMENT_CLIENT` (the legacy `scope-management` service).

The backend has migrated these scope operations to node-ingestion and maintains server-side backwards compatibility, so the client is the only thing pinning us to the legacy service for scopes. We want to finish the migration on the client side.

`SCOPE_MANAGEMENT_CLIENT` itself is **not** going away in this ticket — `UniqueUsersService` and `UniqueGroupsService` still depend on it for user/group operations.

## Solution

### Overview

Re-route every scope-related GraphQL call inside `UniqueScopesService` through `INGESTION_CLIENT`. GraphQL operation documents, variables, and error handling stay identical — only the transport target changes. Because node-ingestion exposes the same scope GraphQL schema (with server-side compat), the change is a one-file rewire on the client.

The `SCOPE_MANAGEMENT_CLIENT` token, its factory in `unique-api.module.ts`, the `scopeManagementServiceBaseUrl` config, and the corresponding helm values stay in place because users/groups still need them. A future ticket can remove them once those services also migrate.

### Architecture

**Single file change.** `services/sharepoint-connector/src/unique-api/unique-scopes/unique-scopes.service.ts`:

- Remove the `@Inject(SCOPE_MANAGEMENT_CLIENT) scopeManagementClient` field from the constructor.
- Replace every `this.scopeManagementClient.request(...)` with `this.ingestionClient.request(...)` across `createScopesBasedOnPaths`, `updateScopeExternalId`, `updateScopeParent`, `createScopeAccesses`, `deleteScopeAccesses`, `getScopeById`, `getScopeByExternalId`, `listChildrenScopes`, `listScopesByExternalIdPrefix`, `deleteScope`.
- `bulkMoveScopes` is already on `ingestionClient` and stays untouched.

**Untouched.** `SCOPE_MANAGEMENT_CLIENT` token, its factory, `scopeManagementServiceBaseUrl` config, `unique-scopes.consts.ts` GraphQL documents, `UniqueUsersService`, `UniqueGroupsService`, helm/terraform.

**Data flow after:** SharePoint sync → `UniqueScopesService` → `ingestionClient` → `node-ingestion` (all scope ops, including `bulkMove`). User/group ops continue through `scopeManagementClient` → `scope-management`.

### Error Handling

No behavioral change. Each call already routes errors through `normalizeError` / per-operation `logSafeKeys`. The `bulkMove` error sanitizer stays as-is. Because operation shapes and HTTP semantics are identical on node-ingestion (server-side compat), no new error classes or retry logic are required. A log-shape regression on a specific error message would be discovered and addressed reactively.

### Testing Strategy

Existing spec `unique-scopes.service.spec.ts` (already rewritten behaviorally per UN-20464) is the right place:

- Drop the scope-management client mock from the test fixture.
- Re-point every assertion previously checking `scopeManagementClientMock.request` to `ingestionClientMock.request`. Mutation/query documents and variable shapes asserted stay identical.
- `bulkMoveScopes` tests stay as-is.

No new test cases are needed — same behavior over a different wire. Validation gate: `pnpm check-all --filter=@unique-ag/sharepoint-connector`. The PR description should call out a staging sync run (create / update / delete / list / access ops) as the highest-signal end-to-end check before merge.

### Surrounding Artifacts Impact

- **Docs:** none — no README/architecture doc names scope-management as the destination for scope ops; the DI module and service are self-documenting via their imports.
- **Helm charts:** none — `scopeManagementServiceBaseUrl` is still required for users/groups; `nodeIngestionServiceBaseUrl` is already wired and serving `bulkMove`.
- **Terraform modules:** none — no IAM, networking, or managed-service changes.
- **Other deployment surface:** none — no CI changes, no feature flag, no migration script. Rollback is a normal revert (server-side compat means traffic returning to scope-management still works if needed).

## Out of Scope

- Removing `SCOPE_MANAGEMENT_CLIENT`, its factory, or `scopeManagementServiceBaseUrl`. Users/groups still depend on them.
- Touching `confluence-connector` or any other consumer of scope-management. Explicitly scoped to sharepoint-connector.
- Adding a feature flag / per-environment toggle. Server-side compat removes the need.
- Refactoring `UniqueScopesService` into per-operation handlers (CQRS per CLAUDE.md). Unrelated to this migration.
- Updating any shared `packages/unique-api` scopes facade. Sharepoint-connector doesn't call through it for these ops.

## Tasks

1. **Re-route scope operations in `UniqueScopesService` to `INGESTION_CLIENT`.** Drop the `SCOPE_MANAGEMENT_CLIENT` injection from `unique-scopes.service.ts` and switch every `this.scopeManagementClient.request(...)` call (everything except the already-migrated `bulkMoveScopes`) to `this.ingestionClient.request(...)`. No changes to GraphQL documents, variables, error handling, or `unique-api.module.ts`.

2. **Update `unique-scopes.service.spec.ts` to mirror the new wiring.** Drop the scope-management client mock from the test fixture and re-point every assertion that checked `scopeManagementClientMock.request` to `ingestionClientMock.request`. Run `pnpm check-all --filter=@unique-ag/sharepoint-connector` to confirm.
