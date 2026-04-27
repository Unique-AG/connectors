import { IncomingMessage } from 'node:http';
import path from 'node:path';
import { RequestMethod } from '@nestjs/common';
import type { Params } from 'nestjs-pino';
import { isPlainObject } from 'remeda';
import { sanitizeError } from './sanitize-error';

export const productionTarget = {
  target: 'pino/file',
};

export const developmentTarget = {
  // https://github.com/pinojs/pino-pretty?tab=readme-ov-file#handling-non-serializable-options
  target: path.resolve(__dirname, './development'),
};

export const defaultLoggerOptions: Params = {
  renameContext: process.env.NODE_ENV !== 'production' ? 'caller' : undefined,
  pinoHttp: {
    enabled: true,
    level: 'info',
    redact: {
      paths: [
        'req.headers.authorization',
        'req.headers.x_api_key',
        'req.headers["x-api-key"]',
        'config.headers.Authorization',
        'req.query["api-key"]',
      ],
      censor: () => '[Redacted]',
    },
    serializers: {
      err: sanitizeError,
    },
    customProps: (req: IncomingMessage) => {
      const operationName = getOperationName(req);
      if (operationName) {
        return {
          operationName,
        };
      }
      return {};
    },
    transport: process.env.NODE_ENV !== 'production' ? developmentTarget : productionTarget,
  },
  exclude: [
    {
      method: RequestMethod.GET,
      path: 'probe',
    },
    {
      method: RequestMethod.GET,
      path: 'health',
    },
    {
      method: RequestMethod.GET,
      path: 'metrics',
    },
  ],
};

function getOperationName(req: IncomingMessage): string | undefined {
  if (!('body' in req)) {
    return undefined;
  }

  const { body } = req;
  if (!isPlainObject(body)) {
    return undefined;
  }

  return typeof body.operationName === 'string' ? body.operationName : undefined;
}
