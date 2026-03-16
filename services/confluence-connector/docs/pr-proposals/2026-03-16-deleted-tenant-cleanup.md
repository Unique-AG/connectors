# PR Proposal

## Title
feat(confluence-connector): implement content cleanup for deleted tenants

## Description
- Implement content cleanup when a tenant's status is set to `deleted` — deletes all ingested files and child scopes while preserving the root scope
- Add `getDeletedTenantConfigs()` export to tenant config loader with full config parsing for deleted tenants
- Add `deletedTenants` map and `processDeletedTenants()` to `TenantRegistry`, called by `TenantSyncScheduler` before active tenant syncs
- V2 tenants: delete files by key prefix; V1 tenants: delete files by scope ownership query
- Add `getFileIdsByScope()` to files service for scope-based file deletion
- Skip cleanup if root scope is already empty (no child scopes, no files)
