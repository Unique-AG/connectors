import {
  createApiMethodExtractor,
  elapsedMilliseconds,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
} from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';
import { type Dispatcher, errors, interceptors } from 'undici';
import type { UniqueAuth } from '../auth/unique-auth';
import { BottleneckFactory } from '../core/bottleneck.factory';
import type { RequestMetricAttributes, UniqueApiMetrics } from '../core/observability';

export class IngestionHttpClient {
  private readonly httpClient: Dispatcher;
  private readonly limiter: Bottleneck;
  private readonly extractApiMethod: ReturnType<typeof createApiMethodExtractor>;
  private readonly origin: string;

  public constructor(
    private readonly auth: UniqueAuth,
    private readonly metrics: UniqueApiMetrics,
    private readonly logger: Logger,
    private readonly dispatcher: Dispatcher,
    private readonly bottleneckFactory: BottleneckFactory,
    private readonly options: {
      baseUrl: string;
      rateLimitPerMinute: number;
      clientName?: string;
    },
  ) {
    const ingestionUrl = new URL(this.options.baseUrl);
    this.origin = `${ingestionUrl.protocol}//${ingestionUrl.host}`;

    this.httpClient = this.dispatcher.compose([
      interceptors.retry({
        maxRetries: 3,
        minTimeout: 3_000,
        methods: ['POST'],
        throwOnError: false,
      }),
    ]);

    this.extractApiMethod = createApiMethodExtractor([
      'v2',
      'content',
      'file-diff',
      'scoped',
      'upload',
      'ingestion',
      'ingestion-gen2',
    ]);

    this.limiter = this.bottleneckFactory.createLimiter(
      {
        reservoir: this.options.rateLimitPerMinute,
        reservoirRefreshAmount: this.options.rateLimitPerMinute,
        reservoirRefreshInterval: 60_000,
      },
      IngestionHttpClient.name,
    );
  }

  public async request(
    options: Dispatcher.RequestOptions & { headers?: Record<string, string> },
  ): Promise<Dispatcher.ResponseData> {
    return this.limiter.schedule(() => this.executeRequest(options));
  }

  public async close(): Promise<void> {
    await this.limiter.stop();
  }

  private async executeRequest(
    options: Dispatcher.RequestOptions & { headers?: Record<string, string> },
  ): Promise<Dispatcher.ResponseData> {
    const startTime = Date.now();
    const httpMethod = (options.method || 'GET').toUpperCase();
    const apiMethod = this.extractApiMethod(options.path, httpMethod);

    const baseAttributes: Pick<RequestMetricAttributes, 'operation' | 'target' | 'tenant'> = {
      operation: apiMethod,
      target: 'ingestion',
      ...(this.options.clientName ? { tenant: this.options.clientName } : {}),
    };

    try {
      const authHeaders = await this.auth.getAuthHeaders();
      const result = await this.httpClient.request({
        origin: this.origin,
        ...options,
        headers: {
          'Content-Type': 'application/json',
          ...options.headers,
          ...authHeaders,
        },
      });

      if (result.statusCode >= 400) {
        const body = await result.body.text();
        throw new errors.ResponseError(
          `Response status code ${result.statusCode}`,
          result.statusCode,
          {
            headers: result.headers,
            body,
          },
        );
      }

      const statusCodeClass = getHttpStatusCodeClass(result.statusCode);
      const durationMs = elapsedMilliseconds(startTime);

      this.metrics.requestsTotal.add(1, {
        ...baseAttributes,
        result: 'success',
      });
      this.metrics.requestDurationMs.record(durationMs, {
        ...baseAttributes,
        result: 'success',
        status_code_class: statusCodeClass,
      });

      const slowBucket = getSlowRequestDurationBucket(durationMs);
      if (slowBucket) {
        this.metrics.slowRequestsTotal.add(1, {
          ...baseAttributes,
          duration_bucket: slowBucket,
        });

        this.logger.warn({
          msg: 'Slow Unique API request detected',
          method: httpMethod,
          path: options.path,
          duration: durationMs,
          durationBucket: slowBucket,
        });
      }

      return result;
    } catch (error) {
      const statusCode = error instanceof errors.ResponseError ? error.statusCode : 0;
      const statusCodeClass = getHttpStatusCodeClass(statusCode);
      const durationMs = elapsedMilliseconds(startTime);

      this.metrics.requestsTotal.add(1, { ...baseAttributes, result: 'error' });
      this.metrics.errorsTotal.add(1, {
        ...baseAttributes,
        status_code_class: statusCodeClass,
      });
      this.metrics.requestDurationMs.record(durationMs, {
        ...baseAttributes,
        result: 'error',
        status_code_class: statusCodeClass,
      });

      const slowBucket = getSlowRequestDurationBucket(durationMs);
      if (slowBucket) {
        this.metrics.slowRequestsTotal.add(1, {
          ...baseAttributes,
          duration_bucket: slowBucket,
        });
      }

      this.logger.error({ msg: 'Failed ingestion HTTP request', error });

      throw error;
    }
  }
}
