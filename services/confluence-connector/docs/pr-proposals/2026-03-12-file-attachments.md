# PR Proposal

## Title
feat(confluence-connector): add file attachment ingestion via native Confluence API

## Description
- Add native Confluence Attachment API integration to discover and ingest file attachments per page
- Stream attachment binary content directly from Confluence to Unique write service (no temp files), following SharePoint connector pattern
- Per-tenant configuration: `attachments.enabled`, `allowedExtensions`, `maxFileSizeBytes`
- Attachments participate in existing diff mechanism via `version.when` for incremental sync
- Support both Cloud and Data Center Confluence instances
