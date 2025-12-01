import type { IncomingHttpHeaders } from 'node:http';
import { Logger } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import { redactSiteNameFromPath, smearSiteIdFromPath } from '../../../utils/logging.util';
import { normalizeError } from '../../../utils/normalize-error';

export function createGraphLoggingInterceptor(
  shouldConcealLogs: boolean,
): Dispatcher.DispatcherComposeInterceptor {
  const logger = new Logger('GraphHttpInterceptor');

  return (dispatch) => {
    return (opts, handler) => {
      const requestStartTime = Date.now();
      const { method = 'GET', path } = opts;

      const loggedPath = shouldConcealLogs ? concealPath(path) : path;

      logger.debug({
        msg: 'Graph API request started',
        method,
        path: loggedPath,
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

        onResponseData(controller: Dispatcher.DispatchController, dataChunk: Buffer): void {
          if (statusCode && statusCode >= 400) {
            bodyChunks.push(dataChunk);
          }

          handler.onResponseData?.(controller, dataChunk);
        },

        onResponseError(controller: Dispatcher.DispatchController, error: Error): void {
          const duration = Date.now() - requestStartTime;
          logger.error({
            msg: 'Graph API request failed with error',
            method,
            path: loggedPath,
            error: normalizeError(error).message,
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
              msg: 'Graph API request completed',
              method,
              path: loggedPath,
              statusCode,
              duration,
            });
          } else if (isServerError) {
            const errorBody = Buffer.concat(bodyChunks).toString('utf-8').slice(0, 500);
            logger.error({
              msg: 'Graph API request failed with server error',
              method,
              path: loggedPath,
              statusCode,
              duration,
              errorBody,
            });
          } else if (isClientError) {
            const errorBody = Buffer.concat(bodyChunks).toString('utf-8').slice(0, 500);
            logger.warn({
              msg: 'Graph API request failed with client error',
              method,
              path: loggedPath,
              statusCode,
              duration,
              errorBody,
            });
          } else {
            logger.warn({
              msg: 'Graph API request completed with unexpected status code',
              method,
              path: loggedPath,
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

function concealPath(path: string | undefined): string {
  if (!path) return 'unknown';

  let result = redactSiteNameFromPath(path);
  result = smearSiteIdFromPath(result);

  return result;
}
