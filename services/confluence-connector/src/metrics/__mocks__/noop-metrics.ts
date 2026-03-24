import type { Metrics } from '../metrics.service';

export function createNoopMetrics(): Metrics {
  return {
    recordSyncDuration: () => {},
    recordScanDuration: () => {},
    recordPagesProcessed: () => {},
    recordAttachmentsProcessed: () => {},
    recordContentDeleted: () => {},
    recordFileDiffEvents: () => {},
    recordAttachmentUploadDuration: () => {},
    recordApiRequestDuration: () => {},
    recordApiError: () => {},
    recordApiThrottleEvent: () => {},
    initializeCounters: () => {},
  } as unknown as Metrics;
}
