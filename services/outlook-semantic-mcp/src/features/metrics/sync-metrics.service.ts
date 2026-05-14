import { Injectable } from '@nestjs/common';
import type { Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import type { FullSyncResult } from '~/features/sync/full-sync/full-sync.types';
import type { LiveCatchupResult } from '~/features/sync/live-catch-up/live-catch-up.types';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { recordInHistogram } from '~/utils/record-in-histogram';

@Injectable()
export class SyncMetricsService {
  private readonly fullSyncRunDuration: Histogram;
  private readonly fullSyncDirectorySyncDuration: Histogram;
  private readonly fullSyncBatchDuration: Histogram;
  private readonly fullSyncGraphPageDuration: Histogram;
  private readonly fullSyncProcessEmailDuration: Histogram;
  private readonly fullSyncMessagesProcessed: Histogram;
  private readonly liveCatchupRunDuration: Histogram;
  private readonly liveCatchupRoundDuration: Histogram;
  private readonly liveCatchupDirectorySyncDuration: Histogram;
  private readonly liveCatchupBatchDuration: Histogram;
  private readonly liveCatchupMessagesProcessed: Histogram;

  public constructor(metricService: MetricService) {
    this.fullSyncRunDuration = metricService.getHistogram('osm_full_sync_run_duration_seconds', {
      description: 'Wall-clock duration of a full sync run() call including retries',
    });
    this.fullSyncDirectorySyncDuration = metricService.getHistogram(
      'osm_full_sync_directory_sync_duration_seconds',
      {
        description: 'Duration of the directory sync step within a full sync',
      },
    );
    this.fullSyncBatchDuration = metricService.getHistogram(
      'osm_full_sync_batch_duration_seconds',
      {
        description: 'Duration of the batch processing step within a full sync',
      },
    );
    this.fullSyncGraphPageDuration = metricService.getHistogram(
      'osm_full_sync_graph_page_duration_seconds',
      {
        description: 'Duration of Graph API page fetch during full sync',
      },
    );
    this.fullSyncProcessEmailDuration = metricService.getHistogram(
      'osm_full_sync_process_email_duration_seconds',
      {
        description: 'Duration of single message ingestion during full sync (including retries)',
      },
    );
    this.fullSyncMessagesProcessed = metricService.getHistogram(
      'osm_full_sync_messages_processed_total',
      {
        description: 'Total messages processed during full sync',
      },
    );
    this.liveCatchupRunDuration = metricService.getHistogram(
      'osm_live_catchup_run_duration_seconds',
      {
        description: 'Wall-clock duration of a total live catch-up run() call',
      },
    );
    this.liveCatchupRoundDuration = metricService.getHistogram(
      'osm_live_catchup_round_duration_seconds',
      {
        description: 'Wall-clock duration of a live catch-up runLiveCatchup() call',
      },
    );
    this.liveCatchupDirectorySyncDuration = metricService.getHistogram(
      'osm_live_catchup_directory_sync_duration_seconds',
      {
        description: 'Duration of directory sync during live catch-up',
      },
    );
    this.liveCatchupBatchDuration = metricService.getHistogram(
      'osm_live_catchup_batch_duration_seconds',
      {
        description: 'Duration of a single batch processing step during live catch-up',
      },
    );
    this.liveCatchupMessagesProcessed = metricService.getHistogram(
      'osm_live_catchup_messages_total',
      {
        description: 'Total messages processed during live catch-up',
      },
    );
  }

  public measureFullSyncRun(fn: () => Promise<FullSyncResult>): Promise<FullSyncResult> {
    return recordInHistogram({
      histogram: this.fullSyncRunDuration,
      successAtrributes: (result) => ({
        status: result.status,
        errorType:
          result.status !== 'failed'
            ? 'none'
            : isRateLimitError(result.error)
              ? 'throttling'
              : 'other',
      }),
      errorAttributtes: (err) => ({
        status: 'failed',
        errorType: isRateLimitError(err) ? 'throttling' : 'other',
      }),
      fn,
    });
  }

  public measureFullSyncDirectorySync<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncDirectorySyncDuration,
      fn,
    });
  }

  public measureFullSyncBatch<T extends { outcome: string }>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncBatchDuration,
      successAtrributes: (r) => ({ outcome: r.outcome }),
      fn,
    });
  }

  public measureGraphPage<T>(fn: () => Promise<T>, pageType: 'first' | 'next'): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncGraphPageDuration,
      attributes: { page_type: pageType },
      fn,
    });
  }

  public measureEmailProcessing<T extends string>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncProcessEmailDuration,
      successAtrributes: (r) => ({ outcome: r === 'failed' ? 'failure' : 'success' }),
      errorAttributtes: () => ({ outcome: 'failure' }),
      fn,
    });
  }

  public countFullSyncMessage<T extends string>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncMessagesProcessed,
      successAtrributes: (r) => ({ outcome: r }),
      fn,
    });
  }

  public measureLiveCatchupRun(fn: () => Promise<LiveCatchupResult>): Promise<LiveCatchupResult> {
    return recordInHistogram({
      histogram: this.liveCatchupRunDuration,
      successAtrributes: (result) => ({
        status: result.status,
        errorType:
          result.status === 'failed'
            ? isRateLimitError(result.err)
              ? 'throttling'
              : 'other'
            : undefined,
      }),
      errorAttributtes: (error) => ({
        status: 'failed',
        errorType: isRateLimitError(error) ? 'throttling' : 'other',
      }),
      fn,
    });
  }

  public measureLiveCatchupRound(fn: () => Promise<LiveCatchupResult>): Promise<LiveCatchupResult> {
    return recordInHistogram({
      histogram: this.liveCatchupRoundDuration,
      successAtrributes: (result) => ({
        status: result.status,
        errorType:
          result.status === 'failed'
            ? isRateLimitError(result.err)
              ? 'throttling'
              : 'other'
            : undefined,
      }),
      errorAttributtes: (error) => ({
        status: 'failed',
        errorType: isRateLimitError(error) ? 'throttling' : 'other',
      }),
      fn,
    });
  }

  public measureLiveCatchupDirectorySync<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupDirectorySyncDuration,
      fn,
    });
  }

  public measureLiveCatchupBatch<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupBatchDuration,
      fn,
    });
  }

  public countLiveCatchupMessage<T extends string>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupMessagesProcessed,
      successAtrributes: (r) => ({ outcome: r }),
      fn,
    });
  }
}
