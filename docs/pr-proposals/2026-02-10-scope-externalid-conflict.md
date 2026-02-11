# PR Proposal

## Ticket

UN-17025

## Title

fix(sharepoint-connector): resolve externalId conflict when folders move within a drive

## Description

- Mark old scopes with a `spc:pending-delete:` externalId prefix when a conflict is detected during scope creation, freeing the externalId for the new scope
- After content sync completes (files moved to new scopes), sweep and delete all scopes marked with the pending-delete prefix, children-first
- Extend `PaginatedScopeQueryInput` to support `startsWith` filter on `externalId`
