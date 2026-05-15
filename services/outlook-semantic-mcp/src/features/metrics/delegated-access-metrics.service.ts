import { Injectable } from '@nestjs/common';
import type { Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { MetricName } from './metric-names';
import { ArgumentsFn, recordInHistogram } from './record-in-histogram';

const getDefaultOnErrorAttributes: ArgumentsFn<unknown> = (err: unknown) => ({
  status: 'failed',
  errorType: isRateLimitError(err) ? 'throttling' : 'other',
});

const getDefaultSuccessAttributes: ArgumentsFn<unknown> = () => ({ status: 'success' });

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
      successAttributes: getDefaultSuccessAttributes,
      errorAttributes: getDefaultOnErrorAttributes,
      fn,
    });
  }

  public measureDiscoverUser<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.discoverUserDuration,
      successAttributes: getDefaultSuccessAttributes,
      errorAttributes: getDefaultOnErrorAttributes,
      fn,
    });
  }

  public measureSyncForAllUsersRun<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.syncForAllUsersRunDuration,
      successAttributes: getDefaultSuccessAttributes,
      errorAttributes: getDefaultOnErrorAttributes,
      fn,
    });
  }

  public measureSyncRun<T>(fn: () => Promise<T>): Promise<T> {
    return recordInHistogram({
      histogram: this.syncRunDuration,
      successAttributes: getDefaultSuccessAttributes,
      errorAttributes: getDefaultOnErrorAttributes,
      fn,
    });
  }
}
