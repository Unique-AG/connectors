# PR Proposal

## Title
refactor(confluence-connector): remove file ingestion and pre-resolve scopes upfront

## Description
- Remove file attachment ingestion feature (`ingestFiles`, `allowedFileExtensions`, MIME types, html-link-parser utility) — not needed for current scope
- Add batch `ensureSpaceScopes()` method to `ScopeManagementService` using `createFromPaths` to resolve all space scopes in one call
- Decouple `IngestionService` from scope management — pass `scopeId` as parameter to `ingestPage()` instead of resolving internally
- Clean up config schema, Helm chart values, constants, and all related tests
