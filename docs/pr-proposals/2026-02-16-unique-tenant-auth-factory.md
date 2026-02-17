# PR Proposal

## Title
feat(confluence-connector): add UniqueTenantAuthFactory and TenantServiceRegistry

## Description
- Add `UniqueTenantAuthFactory` supporting both `cluster_local` (static headers) and `external` (Zitadel OAuth) auth modes with undici retry/redirect, adapted from sharepoint-connector's `UniqueAuthService`
- Introduce `TenantServiceRegistry` — a typed service container keyed by abstract class constructors for per-tenant dependency storage via `AsyncLocalStorage`
- Promote `TenantAuth` and create `UniqueServiceAuth` as abstract classes with `getHeaders()` pattern matching sharepoint-connector and teams-mcp conventions
- Wire both factories through `TenantRegistry` into `TenantContext.services`
