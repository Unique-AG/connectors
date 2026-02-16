# PR Proposal

## Ticket
UN-17171

## Title
feat(confluence-connector): implement multi-tenancy foundation

## Description
- Replace global secret injection with LiteLLM-style `os.environ/VAR_NAME` references resolved inside Zod transforms
- Add `TenantRegistry` with combined `TenantContext` (config + per-tenant auth + logger), replacing single-tenant `ConfigModule` registration and `ConfluenceAuthModule`
- Implement `TenantSyncScheduler` with per-tenant cron jobs; `isScanning` flag lives on `TenantContext`
- Add tenant name extraction from filenames and optional `enabled: false` flag for disabling tenants
