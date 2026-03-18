# PR Proposal

## Title
feat(outlook-semantic-mcp): replace base64 attachments with knowledge base content IDs in create_draft_email

## Description
- Replace the `attachments` (base64) input field with `attachmentIds: string[]` referencing Unique knowledge base content IDs
- Add `downloadContentById` to the `unique-api` `ContentService` and `UniqueContentFacade` to download files from the ingestion service
- Command creates the draft first, then downloads and uploads each attachment sequentially for memory efficiency; failures are reported without blocking the draft
- Update system prompt and Zod schema descriptions with content ID format and examples
