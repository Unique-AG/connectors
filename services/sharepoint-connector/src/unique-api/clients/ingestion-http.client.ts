import { Inject, Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, type Histogram } from '@opentelemetry/api';
import Bottleneck from 'bottleneck';
import { Client, Dispatcher, errors, interceptors } from 'undici';
import { Config } from '../../config';
import {
  createApiMethodExtractor,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
  SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS,
  SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL,
} from '../../metrics';
import { BottleneckFactory } from '../../utils/bottleneck.factory';
import { normalizeError } from '../../utils/normalize-error';
import { elapsedMilliseconds, elapsedSeconds } from '../../utils/timing.util';
import { UniqueAuthService } from '../unique-auth.service';

@Injectable()
export class IngestionHttpClient implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly limiter: Bottleneck;
  private readonly httpClient: Dispatcher;
  private readonly extractApiMethod: ReturnType<typeof createApiMethodExtractor>;

  public constructor(
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
    private readonly bottleneckFactory: BottleneckFactory,
    @Inject(SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS)
    private readonly spcUniqueApiRequestDurationSeconds: Histogram,
    @Inject(SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL)
    private readonly spcUniqueApiSlowRequestsTotal: Counter,
  ) {
    const ingestionUrl = new URL(
      this.configService.get('unique.ingestionServiceBaseUrl', { infer: true }),
    );
    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      // This retry interceptor is specifically tailored to the V2 file-diff calling, as this is
      // currently the only endpoint that we are calling from this client. Even though we're calling
      // POST enpoint there, it's not doing anything on the BE side that would be problematic to
      // retry.
      // If we were to call additional endpoints, we should re-visit this interceptor to be sure it
      // behaves in a way we expect.
      interceptors.retry({
        // We do lower base retry count and higher min timeout to avoid hitting Unique API when it
        // may be already under heavy load. These settings should be enough to get the response in
        // case of some transient errors.
        maxRetries: 3,
        minTimeout: 3_000,
        methods: ['POST'],
        throwOnError: false,
      }),
    ];

    const httpClient = new Client(`${ingestionUrl.protocol}//${ingestionUrl.host}`, {
      bodyTimeout: 30_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    });
    this.httpClient = httpClient.compose(interceptorsInCallingOrder.reverse());

    const apiRateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });

    this.extractApiMethod = createApiMethodExtractor([
      'v2',
      'content',
      'file-diff',
      'scoped',
      'upload',
      // The two segments below are not path of the ingestion service but may occur due to cluster
      // routing based on paths.
      'ingestion',
      'ingestion-gen2',
    ]);

    this.limiter = this.bottleneckFactory.createLimiter(
      {
        reservoir: apiRateLimitPerMinute,
        reservoirRefreshAmount: apiRateLimitPerMinute,
        reservoirRefreshInterval: 60_000,
      },
      'Ingestion HTTP',
    );
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
          http_status_class: statusClass,
        });

        const duration = elapsedMilliseconds(startTime);
        const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
        if (slowRequestDurationBucket) {
          this.spcUniqueApiSlowRequestsTotal.add(1, {
            api_method: apiMethod,
            duration_bucket: slowRequestDurationBucket,
          });

          this.logger.warn({
            msg: 'Slow Unique API request detected',
            method: options.method || 'GET',
            path: options.path,
            duration,
            durationBucket: slowRequestDurationBucket,
          });
        }

        return result;
      } catch (error) {
        const statusCode = error instanceof errors.ResponseError ? error.statusCode : 0;
        const statusClass = getHttpStatusCodeClass(statusCode);

        this.spcUniqueApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
          api_method: apiMethod,
          result: 'error',
          http_status_class: statusClass,
        });

        const duration = elapsedMilliseconds(startTime);
        const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
        if (slowRequestDurationBucket) {
          this.spcUniqueApiSlowRequestsTotal.add(1, {
            api_method: apiMethod,
            duration_bucket: slowRequestDurationBucket,
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
