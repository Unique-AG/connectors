# PR Proposal

## Ticket

UN-15850

## Title

feat(sharepoint-connector): aggregate group permissions for site and library scopes

## Description

- Replace "Root Group" default access on site/library scopes with aggregated group permissions from child files and folders
- Split folder permissions sync into separate queries (data gathering) and command (mapping + syncing)
- Only group permissions are aggregated to top folders; individual user permissions are excluded
- Site scope gets all groups from the entire site; library scope gets groups from that library only
