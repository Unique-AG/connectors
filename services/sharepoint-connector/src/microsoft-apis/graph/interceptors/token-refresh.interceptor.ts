import type { IncomingHttpHeaders } from 'node:http';
import { Logger } from '@nestjs/common';
import { chunk, isArray, isNonNullish, isObjectType } from 'remeda';
import type { Dispatcher } from 'undici';
import { normalizeError } from '../../../utils/normalize-error';

export function createGraphTokenRefreshInterceptor(
  tokenRefreshCallback: () => Promise<string>,
): Dispatcher.DispatcherComposeInterceptor {
  const logger = new Logger('GraphTokenRefreshInterceptor');

  return (dispatch) => {
    return (opts, handler) => {
      let statusCode: number | undefined;
      const bodyChunks: Buffer[] = [];
      let hasRetried = false;

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

          if (responseStatusCode === 401) {
            bodyChunks.length = 0;
            return;
          }

          handler.onResponseStart?.(controller, responseStatusCode, headers, statusMessage);
        },

        onResponseData(controller: Dispatcher.DispatchController, dataChunk: Buffer): void {
          if (statusCode === 401) {
            bodyChunks.push(dataChunk);
            return;
          }

          handler.onResponseData?.(controller, dataChunk);
        },

        onResponseError(controller: Dispatcher.DispatchController, error: Error): void {
          handler.onResponseError?.(controller, error);
        },

        onResponseEnd(
          controller: Dispatcher.DispatchController,
          headers: IncomingHttpHeaders,
        ): void {
          if (statusCode !== 401 || hasRetried) {
            handler.onResponseEnd?.(controller, headers);
            return;
          }

          hasRetried = true;

          const errorBody = Buffer.concat(bodyChunks).toString('utf-8');
          const isTokenExpired = isTokenExpiredError(errorBody);
          if (!isTokenExpired) {
            handler.onResponseEnd?.(controller, headers);
            return;
          }

          logger.log('Token expired, refreshing token...');

          tokenRefreshCallback()
            .then((newAccessToken) => {
              if (!newAccessToken) {
                handler.onResponseEnd?.(controller, headers);
                return;
              }

              const updatedHeaders = updateAuthorizationHeader(opts.headers, newAccessToken);
              logger.log('Token refreshed, retrying request...');
              dispatch({ ...opts, headers: updatedHeaders }, handler);
            })
            .catch((error) => {
              logger.error({
                msg: 'Failed to refresh token or retry request',
                error: normalizeError(error).message,
              });
              handler.onResponseEnd?.(controller, headers);
            });
        },
      };

      return dispatch(opts, wrappedHandler);
    };
  };
}

function isTokenExpiredError(errorBody: string): boolean {
  return (
    errorBody.includes('InvalidAuthenticationToken') ||
    errorBody.includes('Lifetime validation failed') ||
    errorBody.includes('token is expired') ||
    errorBody.includes('Access token has expired')
  );
}

function isArrayHeadersTuple(
  headers: Dispatcher.DispatchOptions['headers'],
): headers is [string, string][] {
  return isArray(headers) && headers.length > 0 && isArray(headers[0]) && headers[0].length === 2;
}

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
