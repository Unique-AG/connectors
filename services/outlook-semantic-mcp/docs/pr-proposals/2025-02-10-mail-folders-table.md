# PR Proposal

## Ticket

UN-16561

## Title

feat(outlook-semantic-mcp): add mail_folders table for Outlook folder-to-scope mapping

## Description

- Add `mail_folders` Drizzle table to mirror Outlook folder hierarchy and link each folder to a Unique scope
- Include self-referencing `parentId` FK for parent-child tree structure, `userProfileId` FK, and uniqueness constraints on `(userProfileId, microsoftId)` and `uniqueScopeId`
- Generate corresponding Drizzle migration
