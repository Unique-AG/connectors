# PR Proposal

## Ticket
UN-18296

## Title
fix(confluence-connector): clean up orphaned files and scopes when spaces are removed

## Description
- Detect removed Confluence spaces by comparing existing scope children against discovered spaceKeys after each sync
- Delete orphaned files via `files.deleteByKeyPrefix` and scopes via `scopes.delete` for spaces no longer in discovery
- Enrich scope externalId to include Confluence spaceId (`confc:{tenant}:{spaceId}:{spaceKey}`) so partialKey can be reconstructed for removed spaces
- Add per-space error handling so one cleanup failure does not block others
