# PR Proposal

## Title

feat(sharepoint-connector): detect and migrate scopes when root scope ID changes

## Description

- Add `RootScopeMigrationService` to detect when `UNIQUE_SCOPE_ID` changes and migrate child scopes to new root
- Extend `UniqueScopesService` with `getScopeByExternalId` and `updateScopeParent` methods
- Migration is resumable via `externalId` state checks - partial migrations continue on next sync
- Failed migrations cause site sync to skip, allowing retry on next cycle
