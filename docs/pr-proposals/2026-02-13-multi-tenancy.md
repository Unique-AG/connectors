# PR Proposal

## Ticket
UN-17171

## Title
feat(confluence-connector): implement multi-tenancy foundation

## Description
- Replace global secret injection with LiteLLM-style `os.environ/VAR_NAME` references resolved inside Zod transforms; env resolver defers validation to schema (required/optional)
- Add `TenantRegistry` with combined `TenantContext` (config + per-tenant auth + logger), replacing single-tenant `ConfigModule` registration and `ConfluenceAuthModule`
- Implement `AsyncLocalStorage`-based tenant context propagation — scheduler sets context once per sync, downstream services access implicitly
- Implement `TenantSyncScheduler` with per-tenant cron jobs; `isScanning` flag lives on `TenantContext`
- Add tenant name extraction from filenames with regex validation (`^[a-z0-9]+(-[a-z0-9]+)*$`) and uniqueness check
- Add `status` field (`active` | `inactive` | `deleted`) for tenant lifecycle management following SPC pattern
