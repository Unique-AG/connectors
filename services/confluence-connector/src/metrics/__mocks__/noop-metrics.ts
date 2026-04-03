import type { Metrics } from '../metrics.service';

type PublicMethodKeys<T> = {
  [K in keyof T]: T[K] extends (...args: never[]) => unknown ? K : never;
}[keyof T];

const noop = () => {};

/**
 * Type-safe noop implementation of Metrics for tests.
 * Adding a new public method to Metrics without adding it here will cause a type error.
 */
export function createNoopMetrics(): Metrics {
  const noopRecord: Record<PublicMethodKeys<Metrics>, () => void> = {
    recordSyncDuration: noop,
    recordScanDuration: noop,
    recordPagesProcessed: noop,
    recordAttachmentsProcessed: noop,
    recordContentDeleted: noop,
    recordFileDiffEvents: noop,
    recordAttachmentUploadDuration: noop,
    recordApiRequestDuration: noop,
    recordApiError: noop,
    recordApiThrottleEvent: noop,
    initializeCounters: noop,
  };

  return noopRecord as unknown as Metrics;
}
