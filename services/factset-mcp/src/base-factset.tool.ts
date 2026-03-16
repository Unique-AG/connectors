import type { Counter, Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import * as z from 'zod';
import { type FactsetClientCredentials } from './auth/factset.client-credentials';

const FactsetApis = z.enum(['fundamentals', 'estimates', 'global-prices', 'street-account-news']);
type FactsetApis = z.infer<typeof FactsetApis>;

function getStatusClass(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) {
    return '2xx';
  }
  if (statusCode >= 300 && statusCode < 400) {
    return '3xx';
  }
  if (statusCode >= 400 && statusCode < 500) {
    return '4xx';
  }
  if (statusCode >= 500) {
    return '5xx';
  }
  return 'unknown';
}

export abstract class BaseFactsetTool {
  protected readonly actionCounter: Counter;
  protected readonly actionFailureCounter: Counter;
  protected readonly requestCounter: Counter;
  protected readonly requestDuration: Histogram;

  protected constructor(
    protected readonly factsetCredentials: FactsetClientCredentials,
    protected readonly metricService: MetricService,
  ) {
    this.actionCounter = metricService.getCounter('factset_actions_total', {
      description: 'Total number of Factset actions',
    });
    this.actionFailureCounter = metricService.getCounter('factset_action_failures_total', {
      description: 'Total number of Factset action failures',
    });
    this.requestCounter = metricService.getCounter('factset_request_total', {
      description: 'Total number of Factset requests',
    });
    this.requestDuration = metricService.getHistogram('factset_request_duration_seconds', {
      description: 'Factset request duration in seconds',
    });
  }

  protected async getFactsetRequestOptions(): Promise<RequestInit> {
    return {
      headers: {
        Authorization: `Bearer ${await this.factsetCredentials.getAccessToken()}`,
      },
    };
  }

  protected async callFactsetApiWithMetrics<T, A>(
    action: string,
    api: FactsetApis,
    fn: (args: A, options: RequestInit) => Promise<T & { status: number }>,
    args: A,
  ): Promise<T> {
    const startTime = Date.now();

    const response = await fn(args, await this.getFactsetRequestOptions());

    const duration = Date.now() - startTime;
    const statusCode = response.status;
    const statusClass = getStatusClass(statusCode);

    if (this.requestCounter) {
      this.requestCounter.add(1, {
        status_class: statusClass,
        action,
        api,
      });
    }
    if (this.requestDuration) {
      this.requestDuration.record(duration / 1000, {
        action,
        api,
      });
    }

    return response;
  }

  protected incrementActionCounter(action: string, api: FactsetApis) {
    if (this.actionCounter) {
      this.actionCounter.add(1, { action, api });
    }
  }

  protected incrementActionFailureCounter(action: string, api: FactsetApis, reason: string) {
    if (this.actionFailureCounter) {
      this.actionFailureCounter.add(1, { action, api, reason });
    }
  }
}
