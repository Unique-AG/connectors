import type { Counter, Histogram, Meter } from '@opentelemetry/api';
import { isObjectType } from 'remeda';

export interface UniqueApiMetrics {
  requestsTotal: Counter;
  errorsTotal: Counter;
  requestDurationMs: Histogram;
  slowRequestsTotal: Counter;
  authTokenRefreshTotal: Counter;
}

export function createUniqueApiMetrics(meter: Meter, prefix: string): UniqueApiMetrics {
  return {
    requestsTotal: meter.createCounter(`${prefix}_requests_total`, {
      description: 'Total number of Unique API requests',
    }),
    errorsTotal: meter.createCounter(`${prefix}_errors_total`, {
      description: 'Total number of Unique API errors',
    }),
    requestDurationMs: meter.createHistogram(`${prefix}_request_duration_ms`, {
      description: 'Duration of Unique API requests in milliseconds',
      unit: 'ms',
    }),
    slowRequestsTotal: meter.createCounter(`${prefix}_slow_requests_total`, {
      description: 'Total number of slow Unique API requests by duration bucket',
    }),
    authTokenRefreshTotal: meter.createCounter(`${prefix}_auth_token_refresh_total`, {
      description: 'Total number of auth token refreshes',
    }),
  };
}

export function getSlowRequestDurationBucket(durationMs: number): string | null {
  if (durationMs > 10_000) return '>10s';
  if (durationMs > 5_000) return '>5s';
  if (durationMs > 2_000) return '>2s';
  if (durationMs > 1_000) return '>1s';
  return null;
}

export interface RequestMetricAttributes {
  operation: string;
  target: string;
  result: 'success' | 'error';
  status_code_class?: string;
  tenant?: string;
}

export function getStatusCodeClass(statusCode: number): string {
  if (statusCode === 0) return 'unknown';
  const cls = Math.floor(statusCode / 100);
  return `${cls}xx`;
}

export function getErrorCodeFromGraphqlRequest(error: unknown): number {
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
