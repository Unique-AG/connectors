import type { IncomingHttpHeaders } from 'node:http';
import { Logger } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import { smearSharepointRestPath } from '../../utils/logging.util';
import { sanitizeError } from '../../utils/normalize-error';
import { extractODataErrorCode } from './odata-error';

export function createLoggingInterceptor(
  shouldConcealLogs: boolean,
): Dispatcher.DispatcherComposeInterceptor {
  const logger = new Logger('SharepointRestHttpInterceptor');

  return (dispatch) => {
    return (opts, handler) => {
      const requestStartTime = Date.now();
      const { method = 'GET', path } = opts;

      logger.debug({
        msg: 'SharePoint REST request started',
        method,
        path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
      });

      let statusCode: number | undefined;
      const bodyChunks: Buffer[] = [];

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

          if (statusCode >= 400) {
            bodyChunks.length = 0;
          }

          handler.onResponseStart?.(controller, responseStatusCode, headers, statusMessage);
        },

        onResponseData(controller: Dispatcher.DispatchController, chunk: Buffer): void {
          if (statusCode && statusCode >= 400) {
            bodyChunks.push(chunk);
          }

          handler.onResponseData?.(controller, chunk);
        },

        onResponseError(controller: Dispatcher.DispatchController, error: Error): void {
          const duration = Date.now() - requestStartTime;
          logger.error({
            msg: 'SharePoint REST request failed with error',
            method,
            path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
            error: sanitizeError(error),
            duration,
          });
          handler.onResponseError?.(controller, error);
        },

        onResponseEnd(
          controller: Dispatcher.DispatchController,
          trailers: IncomingHttpHeaders,
        ): void {
          const duration = Date.now() - requestStartTime;

          if (statusCode === undefined) {
            handler.onResponseEnd?.(controller, trailers);
            return;
          }

          const isSuccess = statusCode >= 200 && statusCode < 400;
          const isServerError = statusCode >= 500;
          const isClientError = statusCode >= 400 && statusCode < 500;

          if (isSuccess) {
            logger.debug({
              msg: 'SharePoint REST request completed',
              method,
              path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
              statusCode,
              duration,
            });
          } else if (isServerError) {
            logger.error({
              msg: 'SharePoint REST request failed with server error',
              method,
              path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
              statusCode,
              duration,
              ...describeErrorBody(bodyChunks, shouldConcealLogs),
            });
          } else if (isClientError) {
            logger.warn({
              msg: 'SharePoint REST request failed with client error',
              method,
              path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
              statusCode,
              duration,
              ...describeErrorBody(bodyChunks, shouldConcealLogs),
            });
          } else {
            logger.warn({
              msg: 'SharePoint REST request completed with unexpected status code',
              method,
              path: shouldConcealLogs ? smearSharepointRestPath(path) : path,
              statusCode,
              duration,
            });
          }

          handler.onResponseEnd?.(controller, trailers);
        },
      };

      return dispatch(opts, wrappedHandler);
    };
  };
}

function describeErrorBody(
  bodyChunks: Buffer[],
  shouldConcealLogs: boolean,
): { errorBody: string } | { errorCode: string | undefined } {
  const body = Buffer.concat(bodyChunks).toString('utf-8');
  if (!shouldConcealLogs) {
    return { errorBody: body.slice(0, 500) };
  }
  return { errorCode: extractODataErrorCode(parseJsonOrUndefined(body)) };
}

function parseJsonOrUndefined(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}
