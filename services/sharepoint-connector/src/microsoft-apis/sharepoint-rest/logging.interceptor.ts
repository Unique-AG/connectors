import type { IncomingHttpHeaders } from 'node:http';
import { Logger } from '@nestjs/common';
import type { Dispatcher } from 'undici';
import { redactSiteNameFromPath } from '../../utils/logging.util';
import { normalizeError } from '../../utils/normalize-error';

export function createLoggingInterceptor(): Dispatcher.DispatcherComposeInterceptor {
  const logger = new Logger('SharepointRestHttpInterceptor');

  return (dispatch) => {
    return (opts, handler) => {
      const requestStartTime = Date.now();
      const { method = 'GET', path } = opts;

      logger.debug({
        msg: 'SharePoint REST request started',
        method,
        path: redactSiteNameFromPath(path),
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
            path: redactSiteNameFromPath(path),
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
              msg: 'SharePoint REST request completed',
              method,
              path: redactSiteNameFromPath(path),
              statusCode,
              duration,
            });
          } else if (isServerError) {
            const errorBody = Buffer.concat(bodyChunks).toString('utf-8').slice(0, 500);
            logger.error({
              msg: 'SharePoint REST request failed with server error',
              method,
              path: redactSiteNameFromPath(path),
              statusCode,
              duration,
              errorBody,
            });
          } else if (isClientError) {
            const errorBody = Buffer.concat(bodyChunks).toString('utf-8').slice(0, 500);
            logger.warn({
              msg: 'SharePoint REST request failed with client error',
              method,
              path: redactSiteNameFromPath(path),
              statusCode,
              duration,
              errorBody,
            });
          } else {
            logger.warn({
              msg: 'SharePoint REST request completed with unexpected status code',
              method,
              path: redactSiteNameFromPath(path),
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
