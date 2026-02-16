import {
  createApiMethodExtractor,
  elapsedMilliseconds,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
  sanitizeError,
} from '@unique-ag/utils';
import Bottleneck from 'bottleneck';
import { type Dispatcher, errors, interceptors } from 'undici';
import type { UniqueAuth } from '../auth/unique-auth';
import type { RequestMetricAttributes, UniqueApiMetrics } from '../core/observability';

const DEFAULT_RATE_LIMIT_PER_MINUTE = 1000;

interface IngestionHttpClientDeps {
  baseUrl: string;
  auth: UniqueAuth;
  metrics: UniqueApiMetrics;
  logger: { warn: (obj: object) => void; error: (obj: object) => void };
  rateLimitPerMinute?: number;
  dispatcher: Dispatcher;
  clientName?: string;
}

export class IngestionHttpClient {
  private readonly httpClient: Dispatcher;
  private readonly limiter: Bottleneck;
  private readonly extractApiMethod: ReturnType<typeof createApiMethodExtractor>;
  private readonly origin: string;
  private readonly auth: UniqueAuth;
  private readonly metrics: UniqueApiMetrics;
  private readonly logger: IngestionHttpClientDeps['logger'];
  private readonly clientName?: string;

  public constructor(deps: IngestionHttpClientDeps) {
    this.auth = deps.auth;
    this.metrics = deps.metrics;
    this.logger = deps.logger;
    this.clientName = deps.clientName;

    const ingestionUrl = new URL(deps.baseUrl);
    this.origin = `${ingestionUrl.protocol}//${ingestionUrl.host}`;

    this.httpClient = deps.dispatcher.compose([
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

    const rateLimitPerMinute = deps.rateLimitPerMinute ?? DEFAULT_RATE_LIMIT_PER_MINUTE;
    this.limiter = new Bottleneck({
      reservoir: rateLimitPerMinute,
      reservoirRefreshAmount: rateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });
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
      ...(this.clientName ? { tenant: this.clientName } : {}),
    };

    try {
      const authHeaders = await this.auth.getAuthHeaders();
      const result = await this.httpClient.request({
        origin: this.origin,
        ...options,
        headers: {
          ...options.headers,
          ...authHeaders,
          'Content-Type': 'application/json',
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

      this.metrics.requestsTotal.add(1, { ...baseAttributes, result: 'success' });
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

      this.logger.error({
        msg: 'Failed ingestion HTTP request',
        error: sanitizeError(error),
      });

      throw error;
    }
  }
}
