import { Injectable } from '@nestjs/common';

export type BatchResult =
  | { outcome: 'batch-uploaded' }
  | { outcome: 'completed' }
  | { outcome: 'version-mismatch' };

/**
 * Processes a single burst of messages (up to 100) for a full sync.
 *
 * Responsibilities (to be implemented in Task 3):
 * - Fetch current Graph API page using saved fullSyncNextLink
 * - Resume from saved fullSyncBatchIndex within the page
 * - For each message (up to 100 per burst):
 *   - Call ingestion API directly (3 retries, exponential backoff)
 *   - On success: increment scheduledForIngestion, save batch index
 *   - On failure after retries: clean up registered content, increment failedToUploadForIngestion
 *   - If message filtered: increment skippedMessages
 *   - Update heartbeat
 *   - Check version — exit early on mismatch
 * - After 100 uploads: return { outcome: 'batch-uploaded' }
 * - If page exhausted: save nextLink, reset batch index to 0, continue to next page
 * - If all pages done: return { outcome: 'completed' }
 * - On version mismatch: return { outcome: 'version-mismatch' }
 */
@Injectable()
export abstract class FullSyncBatchService {
  abstract processBatch(params: {
    userProfileId: string;
    version: string;
  }): Promise<BatchResult>;
}
