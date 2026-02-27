# PR Proposal

## Ticket

UN-17398

## Title

feat(sharepoint-connector): recursively discover and sync subsite content

## Description

- Add recursive subsite discovery via `GET /sites/{siteId}/sites` Graph API endpoint
- Fetch drives and ASPX pages from all discovered subsites, merging them into the parent site's sync
- Scope paths automatically mirror the subsite hierarchy thanks to existing URL-based path extraction
- Extend orphan scope cleanup to cover subsite scope IDs
