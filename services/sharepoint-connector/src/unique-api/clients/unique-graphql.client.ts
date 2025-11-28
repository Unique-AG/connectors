import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { type Counter, type Histogram, ValueType } from '@opentelemetry/api';
import Bottleneck from 'bottleneck';
import type { RequestDocument, RequestOptions, Variables } from 'graphql-request';
import { GraphQLClient } from 'graphql-request';
import { MetricService } from 'nestjs-otel';
import { isObjectType } from 'remeda';
import { Config } from '../../config';
import {
  getDurationBucket,
  getHttpStatusCodeClass,
  REQUEST_DURATION_BUCKET_BOUNDARIES,
} from '../../utils/metrics.util';
import { normalizeError } from '../../utils/normalize-error';
import { elapsedMilliseconds, elapsedSeconds } from '../../utils/timing.util';
import { UniqueAuthService } from '../unique-auth.service';

export const INGESTION_CLIENT = Symbol('INGESTION_CLIENT');
export const SCOPE_MANAGEMENT_CLIENT = Symbol('SCOPE_MANAGEMENT_CLIENT');

export type UniqueGraphqlClientTarget = 'ingestion' | 'scopeManagement';

@Injectable()
export class UniqueGraphqlClient {
  private readonly logger = new Logger(this.constructor.name);
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;

  private readonly spcUniqueApiRequestDurationSeconds: Histogram;
  private readonly spcUniqueApiSlowRequestsTotal: Counter;

  public constructor(
    private readonly clientTarget: UniqueGraphqlClientTarget,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly configService: ConfigService<Config, true>,
    metricService: MetricService,
  ) {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    const graphqlUrl = `${uniqueConfig[`${clientTarget}ServiceBaseUrl`]}/graphql`;

    this.graphQlClient = new GraphQLClient(graphqlUrl, {
      requestMiddleware: async (request) => {
        const additionalHeaders = await this.getAdditionalHeaders();

        return {
          ...request,
          headers: {
            ...request.headers,
            ...additionalHeaders,
            'Content-Type': 'application/json',
          },
        };
      },
    });

    const apiRateLimitPerMinute = this.configService.get('unique.apiRateLimitPerMinute', {
      infer: true,
    });
    this.limiter = new Bottleneck({
      reservoir: apiRateLimitPerMinute,
      reservoirRefreshAmount: apiRateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });

    this.spcUniqueApiRequestDurationSeconds = metricService.getHistogram(
      'spc_unique_graphql_api_request_duration_seconds',
      {
        description: 'Request latency for Unique GraphQL API calls',
        valueType: ValueType.DOUBLE,
        advice: {
          explicitBucketBoundaries: REQUEST_DURATION_BUCKET_BOUNDARIES,
        },
      },
    );

    this.spcUniqueApiSlowRequestsTotal = metricService.getCounter(
      'spc_unique_graphql_api_slow_requests_total',
      {
        description: 'Number of slow Unique GraphQL API calls',
        valueType: ValueType.INT,
      },
    );
  }

  public async request<T, V extends Variables = Variables>(
    document: RequestDocument,
    variables?: V,
  ): Promise<T> {
    return await this.limiter.schedule(async () => {
      const startTime = Date.now();
      const operationName = this.extractOperationName(document);
      const apiMethod = `graphql:${this.clientTarget}:${operationName}`;

      try {
        // However I tried to type variables, I always got an error, no matter how I tried. AI
        // agent wasted good 15 minutes on this and also didn't find a solution. For such internal
        // call and with such weird typing I think it's okay to use hard type casting.
        const options = { document, variables } as unknown as RequestOptions<V, T>;
        const result = await this.graphQlClient.request<T, V>(options);

        this.spcUniqueApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
          api_method: apiMethod,
          result: 'success',
          http_status_class: '2xx',
        });

        const duration = elapsedMilliseconds(startTime);
        const durationBucket = getDurationBucket(duration);
        if (durationBucket) {
          this.spcUniqueApiSlowRequestsTotal.add(1, {
            api_method: apiMethod,
            duration_bucket: durationBucket,
          });

          this.logger.warn({
            msg: 'Slow Unique GraphQL request detected',
            target: this.clientTarget,
            operationName,
            duration,
            durationBucket,
          });
        }

        return result;
      } catch (error) {
        const statusCode = this.getErrorCodeFromGraphqlRequest(error);
        const statusClass = getHttpStatusCodeClass(statusCode);

        this.spcUniqueApiRequestDurationSeconds.record(elapsedSeconds(startTime), {
          api_method: apiMethod,
          result: 'error',
          http_status_class: statusClass,
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
          msg: `Failed ${this.clientTarget} request (${operationName}): ${normalizeError(error).message}`,
          operationName,
          error,
        });
        throw error;
      }
    });
  }

  private async getAdditionalHeaders(): Promise<Record<string, string>> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    return uniqueConfig.serviceAuthMode === 'cluster_local'
      ? {
          'x-service-id': 'sharepoint-connector',
          ...uniqueConfig.serviceExtraHeaders,
        }
      : { Authorization: `Bearer ${await this.uniqueAuthService.getToken()}` };
  }

  private extractOperationName(document: RequestDocument): string {
    const query = typeof document === 'string' ? document : (document.loc?.source.body ?? '');
    const match = query.match(/(?:query|mutation|subscription)\s+(\w+)/);
    return match?.[1] ?? 'unknown';
  }

  private getErrorCodeFromGraphqlRequest(error: unknown): number {
    if (!isObjectType(error)) {
      return 0;
    }

    const graphQlError = error as {
      response?: {
        errors?: Array<{
          extensions?: {
            response?: {
              statusCode?: number;
            };
          };
        }>;
      };
    };

    return graphQlError?.response?.errors?.[0]?.extensions?.response?.statusCode ?? 0;
  }
}
