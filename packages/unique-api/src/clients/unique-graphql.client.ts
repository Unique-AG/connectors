import {
  elapsedMilliseconds,
  getErrorCodeFromGraphqlRequest,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
  sanitizeError,
} from '@unique-ag/utils';
import { Logger } from '@nestjs/common';
import Bottleneck from 'bottleneck';
import type { RequestDocument, RequestOptions, Variables } from 'graphql-request';
import { GraphQLClient } from 'graphql-request';
import { type Dispatcher, fetch as undiciFetch } from 'undici';
import type { UniqueAuth } from '../auth/unique-auth';
import { BottleneckFactory } from '../core/bottleneck.factory';
import type { RequestMetricAttributes, UniqueApiMetrics } from '../core/observability';

export type UniqueGraphqlClientTarget = 'ingestion' | 'scopeManagement';

export class UniqueGraphqlClient {
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;

  public constructor(
    private readonly auth: UniqueAuth,
    private readonly metrics: UniqueApiMetrics,
    private readonly logger: Logger,
    private readonly dispatcher: Dispatcher,
    private readonly bottleneckFactory: BottleneckFactory,
    private readonly config: {
      target: UniqueGraphqlClientTarget;
      baseUrl: string;
      rateLimitPerMinute: number;
      clientName?: string;
    },
  ) {
    const graphqlUrl = `${this.config.baseUrl}/graphql`;

    this.graphQlClient = new GraphQLClient(graphqlUrl, {
      fetch: ((url: RequestInfo | URL, options?: RequestInit) =>
        undiciFetch(
          url as Parameters<typeof undiciFetch>[0],
          {
            ...options,
            dispatcher: this.dispatcher,
          } as Parameters<typeof undiciFetch>[1],
        )) as typeof fetch,
      requestMiddleware: async (request) => {
        const authHeaders = await this.auth.getAuthHeaders();
        return {
          ...request,
          headers: {
            ...request.headers,
            ...authHeaders,
            'Content-Type': 'application/json',
          },
        };
      },
    });

    this.limiter = this.bottleneckFactory.createLimiter(
      {
        reservoir: this.config.rateLimitPerMinute,
        reservoirRefreshAmount: this.config.rateLimitPerMinute,
        reservoirRefreshInterval: 60_000,
      },
      UniqueGraphqlClient.name,
    );
  }

  public async request<T, V extends Variables = Variables>(
    document: RequestDocument,
    variables?: V,
  ): Promise<T> {
    return this.limiter.schedule(() => this.executeRequest<T, V>(document, variables));
  }

  public async close(): Promise<void> {
    await this.limiter.stop();
  }

  private async executeRequest<T, V extends Variables = Variables>(
    document: RequestDocument,
    variables?: V,
  ): Promise<T> {
    const startTime = Date.now();
    const operationName = extractOperationName(document);
    const apiMethod = `graphql:${this.config.target}:${operationName}`;

    const baseAttributes: Pick<RequestMetricAttributes, 'operation' | 'target' | 'tenant'> = {
      operation: apiMethod,
      target: this.config.target,
      ...(this.config?.clientName ? { tenant: this.config.clientName } : {}),
    };

    try {
      const options = { document, variables } as unknown as RequestOptions<V, T>;
      const result = await this.graphQlClient.request<T, V>(options);

      const durationMs = elapsedMilliseconds(startTime);

      this.metrics.requestsTotal.add(1, {
        ...baseAttributes,
        result: 'success',
      });
      this.metrics.requestDurationMs.record(durationMs, {
        ...baseAttributes,
        result: 'success',
        status_code_class: '2xx',
      });

      const slowBucket = getSlowRequestDurationBucket(durationMs);
      if (slowBucket) {
        this.metrics.slowRequestsTotal.add(1, {
          ...baseAttributes,
          duration_bucket: slowBucket,
        });

        this.logger.warn({
          msg: 'Slow Unique GraphQL request detected',
          target: this.config.target,
          operationName,
          duration: durationMs,
          durationBucket: slowBucket,
        });
      }

      return result;
    } catch (error) {
      const statusCode = getErrorCodeFromGraphqlRequest(error);
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
        msg: `Failed ${this.config.target} request (${operationName})`,
        operationName,
        error: sanitizeError(error),
      });

      throw error;
    }
  }
}

function extractOperationName(document: RequestDocument): string {
  const query = typeof document === 'string' ? document : (document.loc?.source.body ?? '');
  const match = query.match(/(?:query|mutation|subscription)\s+(\w+)/);
  return match?.[1] ?? 'unknown';
}
