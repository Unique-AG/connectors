import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Counter, Histogram } from '@opentelemetry/api';
import Bottleneck from 'bottleneck';
import { MetricService } from 'nestjs-otel';
import { Client, Dispatcher, errors, interceptors } from 'undici';
import { Config } from '../../config';
import {
  createApiMethodExtractor,
  getDurationBucket,
  getHttpStatusCodeClass,
} from '../../utils/metrics.util';
import { normalizeError } from '../../utils/normalize-error';
import { elapsedMilliseconds, elapsedSeconds } from '../../utils/timing.util';
import { UniqueAuthService } from '../unique-auth.service';

@Injectable()
export class IngestionHttpClient implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;
  private readonly httpClient: Dispatcher;
  private readonly extractApiMethod: ReturnType<typeof createApiMethodExtractor>;

  private readonly spcUniqueApiRequestDurationSeconds: Histogram;
  private readonly spcUniqueApiSlowRequestsTotal: Counter;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
    metricService: MetricService,
  ) {
    const ingestionUrl = new URL(
      this.configService.get('unique.ingestionServiceBaseUrl', { infer: true }),
    );
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        maxRetries: 3,
        throwOnError: false,
      }),
    ];

    const httpClient = new Client(`${ingestionUrl.protocol}//${ingestionUrl.host}`, {
      bodyTimeout: 30000,
      headersTimeout: 30000,
    });
    this.httpClient = httpClient.compose(interceptorsInCallingOrder.reverse());

    const apiRateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });
    this.limiter = new Bottleneck({
      reservoir: apiRateLimitPerMinute,
      reservoirRefreshAmount: apiRateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.spcUniqueApiRequestDurationSeconds = metricService.getHistogram(
      'spc_unique_api_request_duration_seconds',
      {
        description: 'Measure latency of internal Unique API calls',
      },
    );

    this.spcUniqueApiSlowRequestsTotal = metricService.getCounter(
      'spc_unique_api_slow_requests_total',
      {
        description: 'Total number of slow Unique API requests',
      },
    );

    this.extractApiMethod = createApiMethodExtractor([
      'v2',
      'content',
      'file-diff',
      'scoped',
      'upload',
    ]);
  }

  public async onModuleDestroy(): Promise<void> {
    await this.httpClient.close();
  }

  public async request(
    options: Dispatcher.RequestOptions & { headers?: Record<string, string> },
  ): Promise<Dispatcher.ResponseData> {
    return await this.limiter.schedule(async () => {
      const startTime = Date.now();
      const httpMethod = (options.method || 'GET').toUpperCase();
      const apiMethod = this.extractApiMethod(options.path, httpMethod);

      try {
        const result = await this.httpClient.request({
          ...options,
          headers: {
            ...options.headers,
            ...(await this.getHeaders()),
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

        const statusClass = getHttpStatusCodeClass(result.statusCode);

        this.spcUniqueApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
          api_method: apiMethod,
          result: 'success',
          http_status: statusClass,
        });

        const duration = elapsedMilliseconds(startTime);
        const durationBucket = getDurationBucket(duration);
        if (durationBucket) {
          this.spcUniqueApiSlowRequestsTotal.add(1, {
            api_method: apiMethod,
            duration_bucket: durationBucket,
          });

          this.logger.warn({
            msg: 'Slow Unique API request detected',
            method: options.method || 'GET',
            path: options.path,
            duration,
            durationBucket,
          });
        }

        return result;
      } catch (error) {
        const statusCode = error instanceof errors.ResponseError ? error.statusCode : 0;
        const statusClass = getHttpStatusCodeClass(statusCode);

        this.spcUniqueApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
          api_method: apiMethod,
          result: 'error',
          http_status: statusClass,
        });

        const duration = elapsedMilliseconds(startTime);
        const durationBucket = getDurationBucket(duration);
        if (durationBucket) {
          this.spcUniqueApiSlowRequestsTotal.add(1, {
            api_method: apiMethod,
            duration_bucket: durationBucket,
          });
        }

        this.logger.error({
          msg: `Failed ingestion HTTP request: ${normalizeError(error).message}`,
          error,
        });
        throw error;
      }
    });
  }

  private async getHeaders(): Promise<Record<string, string>> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const clientExtraHeaders =
      uniqueConfig.serviceAuthMode === 'cluster_local'
        ? { 'x-service-id': 'sharepoint-connector', ...uniqueConfig.serviceExtraHeaders }
        : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };

    return {
      ...clientExtraHeaders,
      'Content-Type': 'application/json',
    };
  }
}
