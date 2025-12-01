import type { IncomingHttpHeaders } from 'node:http';
import type { Counter, Histogram } from '@opentelemetry/api';
import type { Dispatcher } from 'undici';
import {
  createApiMethodExtractor,
  getHttpStatusCodeClass,
  getSlowRequestDurationBucket,
} from '../../../metrics';
import { elapsedMilliseconds, elapsedSeconds } from '../../../utils/timing.util';

export function createGraphMetricsInterceptor(
  requestDurationHistogram: Histogram,
  throttleEventsCounter: Counter,
  slowRequestsCounter: Counter,
  msTenantId: string,
): Dispatcher.DispatcherComposeInterceptor {
  const extractApiMethod = createApiMethodExtractor([
    'sites',
    'drives',
    'items',
    'children',
    'content',
    'lists',
    'permissions',
    'groups',
    'members',
    'owners',
  ]);

  return (dispatch) => {
    return (opts, handler) => {
      const requestStartTime = Date.now();
      const { method = 'GET', path = '' } = opts;

      const endpoint = extractEndpoint(path);
      const apiMethod = extractApiMethod(endpoint, method);

      let statusCode: number | undefined;
      let isThrottled = false;
      let throttlePolicy = 'unknown';

      const wrappedHandler: Dispatcher.DispatchHandler = {
        ...handler,

        onRequestStart(controller: Dispatcher.DispatchController, context: unknown): void {
          handler.onRequestStart?.(controller, context);
        },

        onResponseStart(
          controller: Dispatcher.DispatchController,
          responseStatusCode: number,
          headers: IncomingHttpHeaders,
          statusMessage?: string,
        ): void {
          statusCode = responseStatusCode;

          if (responseStatusCode === 429) {
            isThrottled = true;
            throttlePolicy = headers['retry-after'] ? 'retry_after' : 'unknown';
          } else if (responseStatusCode === 503 && headers['retry-after']) {
            isThrottled = true;
            throttlePolicy = 'retry_after';
          }

          if (headers['ratelimit-limit']) {
            throttlePolicy = 'rate_limit';
          }

          handler.onResponseStart?.(controller, responseStatusCode, headers, statusMessage);
        },

        onResponseData(controller: Dispatcher.DispatchController, dataChunk: Buffer): void {
          handler.onResponseData?.(controller, dataChunk);
        },

        onResponseError(controller: Dispatcher.DispatchController, error: Error): void {
          const duration = elapsedMilliseconds(requestStartTime);
          const statusClass = getHttpStatusCodeClass(0);

          requestDurationHistogram.record(elapsedSeconds(requestStartTime), {
            ms_tenant_id: msTenantId,
            api_method: apiMethod,
            result: 'error',
            http_status_class: statusClass,
          });

          const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
          if (slowRequestDurationBucket) {
            slowRequestsCounter.add(1, {
              ms_tenant_id: msTenantId,
              api_method: apiMethod,
              duration_bucket: slowRequestDurationBucket,
            });
          }

          handler.onResponseError?.(controller, error);
        },

        onResponseEnd(
          controller: Dispatcher.DispatchController,
          trailers: IncomingHttpHeaders,
        ): void {
          const duration = elapsedMilliseconds(requestStartTime);
          const statusClass = getHttpStatusCodeClass(statusCode ?? 0);
          const isSuccess = statusCode !== undefined && statusCode >= 200 && statusCode < 400;

          requestDurationHistogram.record(elapsedSeconds(requestStartTime), {
            ms_tenant_id: msTenantId,
            api_method: apiMethod,
            result: isSuccess ? 'success' : 'error',
            http_status_class: statusClass,
          });

          if (isThrottled) {
            throttleEventsCounter.add(1, {
              ms_tenant_id: msTenantId,
              api_method: apiMethod,
              policy: throttlePolicy,
            });
          }

          const slowRequestDurationBucket = getSlowRequestDurationBucket(duration);
          if (slowRequestDurationBucket) {
            slowRequestsCounter.add(1, {
              ms_tenant_id: msTenantId,
              api_method: apiMethod,
              duration_bucket: slowRequestDurationBucket,
            });
          }

          handler.onResponseEnd?.(controller, trailers);
        },
      };

      return dispatch(opts, wrappedHandler);
    };
  };
}

function extractEndpoint(path: string | undefined): string {
  if (!path) return 'unknown';

  try {
    const urlPath = path.startsWith('/') ? path : `/${path}`;
    return urlPath.replace(/^\/(v\d+(\.\d+)?|beta)/, '') || '/';
  } catch {
    return 'unknown';
  }
}
