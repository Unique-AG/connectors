import { Injectable } from '@nestjs/common';
import type { Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { MetricName } from './metric-names';
import { ArgumentsFn, recordInHistogram } from './record-in-histogram';

const getDefaultOnErrorAtrributes: ArgumentsFn<unknown> = (err: unknown) => ({
  status: 'failed',
  errorType: isRateLimitError(err) ? 'throttling' : 'other',
});

const getDefaultSuccessAtrributes: ArgumentsFn<unknown> = () => ({ status: 'success' });

@Injectable()
export class DelegatedAccessMetricsService {
  private readonly discoverRunDuration: Histogram;
  private readonly discoverUserDuration: Histogram;
  private readonly syncForAllUsersRunDuration: Histogram;
  private readonly syncRunDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.discoverRunDuration = metricService.getHistogram(
      MetricName.DiscoverDelegatedAccessRunDuration,
      {
        description: 'Wall-clock duration of a full delegated access discovery run',
      },
    );
    this.discoverUserDuration = metricService.getHistogram(
      MetricName.DiscoverDelegatedAccessUserDuration,
      {
        description: 'Duration of delegated access discovery for a single delegate user',
      },
    );
    this.syncForAllUsersRunDuration = metricService.getHistogram(
      MetricName.SyncDelegatedAccessForAllUsersRunDuration,
      {
        description:
          'Wall-clock duration of a full delegated access verification run for all users',
      },
    );
    this.syncRunDuration = metricService.getHistogram(MetricName.SyncDelegatedAccessRunDuration, {
      description: 'Duration of delegated access verification for a single account',
    });
  }

  public measureDiscoverRun<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.discoverRunDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureDiscoverUser<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.discoverUserDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureSyncForAllUsersRun<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.syncForAllUsersRunDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }

  public measureSyncRun<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.syncRunDuration,
      successAtrributes: getDefaultSuccessAtrributes,
      errorAttributtes: getDefaultOnErrorAtrributes,
      fn,
    });
  }
}
