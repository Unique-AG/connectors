import type { Counter, Histogram, Meter } from '@opentelemetry/api';

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
