# PR Proposal

## Title
refactor(confluence-connector): rename TenantAuthFactory to ConfluenceTenantAuthFactory

## Description
- Rename `TenantAuthFactory` to `ConfluenceTenantAuthFactory` to make the Confluence-source-auth domain explicit and avoid ambiguity when Unique/Zitadel auth is added.
- Update file name, barrel exports, DI wiring in `TenantModule`, consumer code in `TenantRegistry`, and all related test files.
- Define naming contract: `ConfluenceTenantAuthFactory` for source auth, `UniqueTenantAuthFactory` reserved for future Unique/Zitadel tenant auth.
