import type { Counter, Histogram } from '@opentelemetry/api';
import type { Metrics } from '../metrics.service';

export function createNoopCounter(): Counter {
  return { add: () => {} } as unknown as Counter;
}

export function createNoopHistogram(): Histogram {
  return { record: () => {} } as unknown as Histogram;
}

export function createNoopMetrics(): Metrics {
  return {
    syncDuration: createNoopHistogram(),
    scanDuration: createNoopHistogram(),
    pagesProcessed: createNoopCounter(),
    attachmentsProcessed: createNoopCounter(),
    contentDeleted: createNoopCounter(),
    fileDiffEvents: createNoopCounter(),
    attachmentUploadDuration: createNoopHistogram(),
    confluenceApiRequestDuration: createNoopHistogram(),
    confluenceApiThrottleEvents: createNoopCounter(),
    confluenceApiErrors: createNoopCounter(),
    initializeCountersForTenant: () => {},
  } as unknown as Metrics;
}
