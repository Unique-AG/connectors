# PR Proposal

## Title
feat(confluence-connector): implement scope-based ingestion with file-diffing

## Description
- Add scope-based (flat) ingestion pipeline: file-diffing, content registration, upload, and finalization for Confluence pages and linked files
- Introduce FileDiffService, IngestionService, and MockUniqueApiClient to support the ingestion flow with mocked Unique API calls
- Extend tenant config schema with ingestion settings (ingestionMode, scopeId, ingestFiles, allowedFileExtensions)
- Wire ingestion into the existing sync orchestration with concurrency control, error handling, and accidental deletion safety checks
