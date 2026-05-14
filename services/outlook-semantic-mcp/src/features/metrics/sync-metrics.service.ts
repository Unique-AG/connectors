import { Injectable } from '@nestjs/common';
import type { Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { ArgumentsFn, recordInHistogram } from '~/features/metrics/record-in-histogram';
import type { BatchResult, FullSyncResult } from '~/features/sync/full-sync/full-sync.types';
import type {
  LiveCatchupResult,
  LiveCathupRoundResult,
} from '~/features/sync/live-catch-up/live-catch-up.types';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { ProcessEmailCommandResult } from '../process-email/process-email.command';
import { MetricName } from './metric-names';

const getDefaultOnErrorAtrributes: ArgumentsFn<unknown> = (err: unknown) => ({
  status: 'failed',
  errorType: isRateLimitError(err) ? 'throttling' : 'other',
});

const getDefaultSuccessAtrributes: ArgumentsFn<unknown> = () => ({ status: 'success' });

@Injectable()
export class SyncMetricsService {
  private readonly fullSyncRunDuration: Histogram;
  private readonly fullSyncDirectorySyncDuration: Histogram;
  private readonly fullSyncBatchDuration: Histogram;
  private readonly fullSyncGraphPageDuration: Histogram;
  private readonly fullSyncProcessEmailDuration: Histogram;
  private readonly liveCatchupRunDuration: Histogram;
  private readonly liveCatchupRoundDuration: Histogram;
  private readonly liveCatchupDirectorySyncDuration: Histogram;
  private readonly liveCatchupBatchDuration: Histogram;
  private readonly liveCatchupMessageDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.fullSyncRunDuration = metricService.getHistogram(MetricName.FullSyncRunDuration, {
      description: 'Wall-clock duration of a full sync run() call including retries',
    });
    this.fullSyncDirectorySyncDuration = metricService.getHistogram(
      MetricName.FullSyncDirectorySyncDuration,
      {
        description: 'Duration of the directory sync step within a full sync',
      },
    );
    this.fullSyncBatchDuration = metricService.getHistogram(MetricName.FullSyncBatchDuration, {
      description: 'Duration of the batch processing step within a full sync',
    });
    this.fullSyncGraphPageDuration = metricService.getHistogram(
      MetricName.FullSyncGraphPageDuration,
      {
        description: 'Duration of Graph API page fetch during full sync',
      },
    );
    this.fullSyncProcessEmailDuration = metricService.getHistogram(
      MetricName.FullSyncProcessEmailDuration,
      {
        description: 'Duration of single message ingestion during full sync (including retries)',
      },
    );
    this.liveCatchupRunDuration = metricService.getHistogram(MetricName.LiveCatchupRunDuration, {
      description: 'Wall-clock duration of a total live catch-up run() call',
    });
    this.liveCatchupRoundDuration = metricService.getHistogram(
      MetricName.LiveCatchupRoundDuration,
      {
        description: 'Wall-clock duration of a live catch-up runLiveCatchup() call',
      },
    );
    this.liveCatchupDirectorySyncDuration = metricService.getHistogram(
      MetricName.LiveCatchupDirectorySyncDuration,
      {
        description: 'Duration of directory sync during live catch-up',
      },
    );
    this.liveCatchupBatchDuration = metricService.getHistogram(
      MetricName.LiveCatchupBatchDuration,
      {
        description: 'Duration of a single batch processing step during live catch-up',
      },
    );
    this.liveCatchupMessageDuration = metricService.getHistogram(
      MetricName.LiveCatchupProcessEmailDuration,
      {
        description: 'Duration of a single messages processed during live catch-up',
      },
    );
  }

  public measureFullSyncRun<T extends FullSyncResult>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncRunDuration,
      successAtrributes: (result) =>
        result.status === 'failed'
          ? getDefaultOnErrorAtrributes(result.error)
          : { status: result.status },
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureFullSyncDirectorySync<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncDirectorySyncDuration,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureFullSyncBatch<T extends BatchResult>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncBatchDuration,
      errorAttributtes: getDefaultOnErrorAtrributes,
      successAtrributes: (result) => ({ status: result.outcome }),
      fn,
    });
  }

  public measureGraphPage<T>(fn: () => Promise<T>, pageType: 'first' | 'next'): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncGraphPageDuration,
      attributes: { page_type: pageType },
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureEmailProcessing<T extends ProcessEmailCommandResult>(
    fn: () => Promise<T>,
  ): Promise<T> {
    return recordInHistogram({
      histogram: this.fullSyncProcessEmailDuration,
      successAtrributes: (result) => ({ status: result }),
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureLiveCatchupRun<T extends LiveCatchupResult>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupRunDuration,
      successAtrributes: (result) =>
        result.status === 'failed'
          ? getDefaultOnErrorAtrributes(result.err)
          : { status: result.status },
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureLiveCatchupRound<T extends LiveCathupRoundResult>(
    fn: () => Promise<T>,
  ): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupRoundDuration,
      successAtrributes: (result) =>
        result.status === 'failed'
          ? getDefaultOnErrorAtrributes(result.err)
          : { status: result.status },
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureLiveCatchupDirectorySync<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupDirectorySyncDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureLiveCatchupBatch<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupBatchDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureLiveCatchupMessageProcessing<T extends ProcessEmailCommandResult>(
    fn: () => Promise<T>,
  ): Promise<T> {
    return recordInHistogram({
      histogram: this.liveCatchupMessageDuration,
      successAtrributes: (r) => ({ status: r }),
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }
}
