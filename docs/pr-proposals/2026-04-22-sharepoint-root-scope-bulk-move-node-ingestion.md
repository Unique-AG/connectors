# PR Proposal — monorepo repo (node-ingestion)

## Title
feat(node-ingestion): allow connector service accounts to call bulkMove

## Description
- Widen `@AllowAccess` on `ScopeOperationJobResolver.bulkMove` to include `Integration.SHAREPOINT_CONNECTOR` and `Integration.CONFLUENCE_CONNECTOR`, matching the access pattern already used by sibling resolvers (`updateScope`, `deleteScope`, `paginatedScope`, `generateScopesBasedOnPaths`) in `scope.resolver.ts`.
- Removes the stale `// todo give access to SPC, Conf-Con, OutlookMCP` comment.
- No behavior change for existing `AccessType.USER` callers; this only opens the resolver to additional authenticated callers.

## Required by
- sharepoint-connector refactor to use `bulkMove` for root-scope migration (connectors repo). This PR must land first.
