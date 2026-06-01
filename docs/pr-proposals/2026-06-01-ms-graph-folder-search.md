# PR Proposal

## Ticket
UN-21097

## Title
feat(outlook-semantic-mcp): add folder filtering for MS Graph KQL email search

## Description
- Add optional `directories` parameter to `MsGraphKqlQuerySchema` so KQL queries can be scoped to specific folders using `/mailFolders/{id}/messages` instead of always hitting the full `/messages` endpoint
- Implement four-case batch request logic: own/full-delegated mailboxes use `/messages` when no folders are specified; directory-only delegated mailboxes fan out into per-folder sub-requests; any explicit `directories` input always routes through `/mailFolders/{id}/messages`
- Replace the `chunk`-based batch loop with a mutable queue that drains on 403/404 (full-mailbox scope for full-access failures, mailbox+folder scope for folder-level failures) and a single retry round for transient errors (429, 5xx, network failures)
- Extract `sanitizeWrongDirectoryIds` as a shared pure-function utility reused by both the MS Graph path and the existing semantic-search cleanup query
- Surface throttle warnings, lost-access notes, and unresolved folder names in `searchSummary`
