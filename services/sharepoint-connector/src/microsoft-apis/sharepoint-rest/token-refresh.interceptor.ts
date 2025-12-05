import type { IncomingHttpHeaders } from 'node:http';
import { Logger } from '@nestjs/common';
import { chunk, isArray, isNonNullish, isObjectType } from 'remeda';
import type { Dispatcher } from 'undici';
import { sanitizeError } from '../../utils/normalize-error';

// This interceptor was mostly vibe-coded based on TokenRefreshMiddleware from graph API.
export function createTokenRefreshInterceptor(
  tokenRefreshCallback: () => Promise<string>,
): Dispatcher.DispatcherComposeInterceptor {
  const logger = new Logger('TokenRefreshInterceptor');

  return (dispatch) => {
    return (opts, handler) => {
      let statusCode: number | undefined;
      const bodyChunks: Buffer[] = [];
      let hasRetried = false;

      const wrappedHandler: Dispatcher.DispatchHandler = {
        ...handler,

        // We need to implement onRequestStart because based on existence of this method unidici
        // determines whether we use old or new callbacks. It should exist on passed handlers but
        // it's apparently not the case so we put it explicitly in case it's missing on handler.
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

          if (responseStatusCode === 401) {
            bodyChunks.length = 0;
            return;
          }

          handler.onResponseStart?.(controller, responseStatusCode, headers, statusMessage);
        },

        onResponseData(controller: Dispatcher.DispatchController, chunk: Buffer): void {
          if (statusCode === 401) {
            bodyChunks.push(chunk);
            return;
          }

          handler.onResponseData?.(controller, chunk);
        },

        onResponseError(controller: Dispatcher.DispatchController, error: Error): void {
          handler.onResponseError?.(controller, error);
        },

        onResponseEnd(
          controller: Dispatcher.DispatchController,
          trailers: IncomingHttpHeaders,
        ): void {
          if (statusCode !== 401 || hasRetried) {
            handler.onResponseEnd?.(controller, trailers);
            return;
          }

          hasRetried = true;

          const errorBody = Buffer.concat(bodyChunks).toString('utf-8');
          const isTokenExpired = isTokenExpiredError(errorBody);
          if (!isTokenExpired) {
            handler.onResponseEnd?.(controller, trailers);
            return;
          }

          logger.log('Token expired, refreshing token...');

          tokenRefreshCallback()
            .then((newAccessToken) => {
              if (!newAccessToken) {
                handler.onResponseEnd?.(controller, trailers);
                return;
              }

              const updatedHeaders = updateAuthorizationHeader(opts.headers, newAccessToken);
              logger.log('Token refreshed, retrying request...');
              dispatch({ ...opts, headers: updatedHeaders }, handler);
            })
            .catch((error) => {
              logger.error({
                msg: 'Failed to refresh token or retry request',
                error: sanitizeError(error),
              });
              handler.onResponseEnd?.(controller, trailers);
            });
        },
      };

      return dispatch(opts, wrappedHandler);
    };
  };
}

function isTokenExpiredError(errorBody: string): boolean {
  return errorBody.includes('token is expired.');
}

function isArrayHeadersTuple(
  headers: Dispatcher.DispatchOptions['headers'],
): headers is [string, string][] {
  return isArray(headers) && headers.length > 0 && isArray(headers[0]) && headers[0].length === 2;
}

// Handling headers in unidici is pretty irritating, because it can be a swath of different types.
// We check and adjust in case of flat array, array of tuples, iterable or plain object.
function updateAuthorizationHeader(
  headers: Dispatcher.DispatchOptions['headers'],
  newAccessToken: string,
): Dispatcher.DispatchOptions['headers'] {
  if (!headers) {
    return { Authorization: `Bearer ${newAccessToken}` };
  }

  let arrayHeaders: [string, string | string[] | undefined][] | null = null;

  if (isArrayHeadersTuple(headers)) {
    arrayHeaders = headers;
  } else if (isArray(headers)) {
    // We have to cast the type, because theoretically the last entry from chunking can be a
    // single value, but in practice headers array will always have even number of elements.
    arrayHeaders = chunk(headers, 2) as [string, string | string[] | undefined][];
  } else if (
    isObjectType(headers) &&
    Symbol.iterator in headers &&
    typeof headers[Symbol.iterator] === 'function'
  ) {
    arrayHeaders = Array.from(headers);
  }

  if (isNonNullish(arrayHeaders)) {
    return [
      ...arrayHeaders.filter(([key]) => key.toLowerCase() !== 'authorization'),
      ['Authorization', `Bearer ${newAccessToken}`],
    ];
  }

  return {
    ...headers,
    Authorization: `Bearer ${newAccessToken}`,
  };
}
