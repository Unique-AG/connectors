# Design: Clean up ingested files left in error state after failed ingestion

**Ticket:** UN-18299

## Problem

When a file or attachment is registered in Unique but the subsequent upload or finalize step fails, the registered content record is left behind in an error state. These orphaned entries accumulate over time with no automatic cleanup.

This affects both `ingestPage()` and `ingestAttachment()` in `IngestionService`, which follow a 3-step flow: `registerContent()` -> upload -> `finalizeIngestion()`. Currently, the catch block only logs the error and moves on.

## Solution

### Overview

Add a private `cleanupFailedRegistration(key, logContext)` helper method to `IngestionService` that deletes the registered content by key when upload or finalization fails. The helper wraps the delete call in its own try-catch so cleanup failures are logged but never crash the pipeline.

Both `ingestPage()` and `ingestAttachment()` are modified to track whether registration succeeded (by capturing the key before the try block and setting a `registered` flag after `registerContent()` returns). In the catch block, if registration succeeded, the cleanup helper is called.

### Architecture

The change is contained entirely within `IngestionService` (`services/confluence-connector/src/synchronization/ingestion.service.ts`):

1. **New private method: `cleanupFailedRegistration(key, logContext)`**
   - Calls `this.deleteContentByKeys([key])` (reuses existing method)
   - Wraps in try-catch: logs error on cleanup failure, never throws
   - Logs a warning on successful cleanup indicating orphaned content was removed

2. **Modified `ingestPage()`**
   - Declare `key` and `registered` flag before the try block
   - Set `registered = true` after `registerContent()` succeeds
   - In catch: if `registered`, call `cleanupFailedRegistration(key, { pageId, title })`

3. **Modified `ingestAttachment()`**
   - Same pattern: declare `key` and `registered` flag before try
   - Set `registered = true` after `registerContent()` succeeds
   - In catch: if `registered`, call `cleanupFailedRegistration(key, { attachmentId, title })`

### Error Handling

- Cleanup is only attempted when registration succeeded (`registered === true`)
- The `cleanupFailedRegistration()` helper has its own try-catch that logs but never throws
- The existing `deleteContentByKeys()` method already handles the case where no content is found for a key (logs warning, returns 0)
- Pipeline continues processing other items regardless of cleanup outcome

### Testing Strategy

Add tests to the existing `ingestion.service.spec.ts` test suite:

- **Page upload fails after registration** -> verify `deleteContentByKeys` is called with the correct key
- **Attachment upload fails after registration** -> verify cleanup is called
- **Finalize fails after registration** -> verify cleanup is called
- **Registration itself fails** -> verify cleanup is NOT called (no regression)
- **Cleanup itself fails** -> verify error is logged, pipeline continues

## Out of Scope

- Refactoring to a step-based pipeline pattern (not needed for this fix)
- Batch cleanup of historically orphaned records (separate concern)
- Retry logic for failed uploads (different ticket)

## Tasks

1. **Add `cleanupFailedRegistration()` helper** - Create a private method on `IngestionService` that takes a content key and log context, calls `deleteContentByKeys([key])`, and wraps in try-catch with appropriate logging.

2. **Update `ingestPage()` to clean up on failure** - Track registration success with a flag, call cleanup helper in the catch block when registration succeeded.

3. **Update `ingestAttachment()` to clean up on failure** - Same pattern as page: track registration, call cleanup in catch block.

4. **Add tests for cleanup behavior** - Add test cases covering: upload failure triggers cleanup, finalize failure triggers cleanup, registration failure skips cleanup, cleanup failure is logged but doesn't crash.
