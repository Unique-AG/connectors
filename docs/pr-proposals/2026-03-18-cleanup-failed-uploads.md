# PR Proposal

## Ticket
UN-18299

## Title
fix(confluence-connector): clean up registered content after failed upload or finalization

## Description
- Add `cleanupFailedRegistration()` helper to `IngestionService` that deletes orphaned content records when upload or finalization fails after successful registration
- Update `ingestPage()` and `ingestAttachment()` to call cleanup on failure, preventing orphaned file records in Unique
- Cleanup errors are logged but do not crash the pipeline
- Add tests covering cleanup on upload failure, finalize failure, registration failure (no cleanup), and cleanup failure resilience
