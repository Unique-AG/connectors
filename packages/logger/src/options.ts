import { IncomingMessage } from 'node:http';
import { RequestMethod } from '@nestjs/common';
import type { Params } from 'nestjs-pino';
import type { PrettyOptions } from 'pino-pretty';

export const productionTarget = {
  target: 'pino/file',
};

export const developmentTarget = {
  target: 'pino-pretty',
  options: {
    translateTime: 'SYS:yyyy-mm-dd HH:MM:ss.l',
    ignore: 'trace_flags,hostname,pid,req',
  } satisfies PrettyOptions,
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
    customProps: (req: IncomingMessage) => {
      if ((req as unknown as { body: { operationName: string } })?.body?.operationName) {
        return {
          operationName: (req as unknown as { body: { operationName: string } }).body.operationName,
        };
      }
      return {};
    },
    transport:
      process.env.NODE_ENV !== 'production' ? developmentTarget : productionTarget,
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
