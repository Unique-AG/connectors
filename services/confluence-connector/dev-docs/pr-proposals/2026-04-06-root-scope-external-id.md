# PR Proposal

## Ticket
UN-18352

## Title
feat(confluence-connector): set external ID on root scope and validate instance ownership

## Description
- Resolve a stable instance identifier for Cloud (`cloudId` from config) and Data Center (`GET /rest/applinks/1.0/manifest` instance UUID)
- Set `externalId` on the root scope during initial sync (`confc:cloud:<id>` or `confc:dc:<id>`)
- Block sync with a fatal error when the root scope is already claimed by a different Confluence instance
- Cache the resolved instance identifier to avoid redundant HTTP calls on subsequent sync cycles
