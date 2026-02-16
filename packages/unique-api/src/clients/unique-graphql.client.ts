import {
  elapsedMilliseconds,
  getErrorCodeFromGraphqlRequest,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
  sanitizeError,
} from '@unique-ag/utils';
import Bottleneck from 'bottleneck';
import type { RequestDocument, RequestOptions, Variables } from 'graphql-request';
import { GraphQLClient } from 'graphql-request';
import { type Dispatcher, fetch as undiciFetch } from 'undici';
import type { UniqueAuth } from '../auth/unique-auth';
import type { RequestMetricAttributes, UniqueApiMetrics } from '../core/observability';

const DEFAULT_RATE_LIMIT_PER_MINUTE = 1000;

export type UniqueGraphqlClientTarget = 'ingestion' | 'scopeManagement';

interface UniqueGraphqlClientDeps {
  target: UniqueGraphqlClientTarget;
  baseUrl: string;
  auth: UniqueAuth;
  metrics: UniqueApiMetrics;
  logger: { warn: (obj: object) => void; error: (obj: object) => void };
  rateLimitPerMinute?: number;
  dispatcher: Dispatcher;
  clientName?: string;
}

export class UniqueGraphqlClient {
  private readonly graphQlClient: GraphQLClient;
  private readonly limiter: Bottleneck;
  private readonly target: UniqueGraphqlClientTarget;
  private readonly auth: UniqueAuth;
  private readonly metrics: UniqueApiMetrics;
  private readonly logger: UniqueGraphqlClientDeps['logger'];
  private readonly clientName?: string;

  public constructor(deps: UniqueGraphqlClientDeps) {
    this.target = deps.target;
    this.auth = deps.auth;
    this.metrics = deps.metrics;
    this.logger = deps.logger;
    this.clientName = deps.clientName;

    const graphqlUrl = `${deps.baseUrl}/graphql`;

    this.graphQlClient = new GraphQLClient(graphqlUrl, {
      fetch: ((url: RequestInfo | URL, options?: RequestInit) =>
        undiciFetch(
          url as Parameters<typeof undiciFetch>[0],
          {
            ...options,
            dispatcher: deps.dispatcher,
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

    const rateLimitPerMinute = deps.rateLimitPerMinute ?? DEFAULT_RATE_LIMIT_PER_MINUTE;
    this.limiter = new Bottleneck({
      reservoir: rateLimitPerMinute,
      reservoirRefreshAmount: rateLimitPerMinute,
      reservoirRefreshInterval: 60_000,
    });
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
    const apiMethod = `graphql:${this.target}:${operationName}`;

    const baseAttributes: Pick<RequestMetricAttributes, 'operation' | 'target' | 'tenant'> = {
      operation: apiMethod,
      target: this.target,
      ...(this.clientName ? { tenant: this.clientName } : {}),
    };

    try {
      const options = { document, variables } as unknown as RequestOptions<V, T>;
      const result = await this.graphQlClient.request<T, V>(options);

      const durationMs = elapsedMilliseconds(startTime);

      this.metrics.requestsTotal.add(1, { ...baseAttributes, result: 'success' });
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
          target: this.target,
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
        msg: `Failed ${this.target} request (${operationName})`,
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
