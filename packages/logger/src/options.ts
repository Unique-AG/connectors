import { IncomingMessage } from 'node:http';
import path from 'node:path';
import { RequestMethod } from '@nestjs/common';
import type { Params } from 'nestjs-pino';
import { isPlainObject } from 'remeda';
import { createSecretRedactor, type SecretRedactionOptions } from './redact-secrets';
import { sanitizeError } from './sanitize-error';

export const productionTarget = {
  target: 'pino/file',
};

export const developmentTarget = {
  // https://github.com/pinojs/pino-pretty?tab=readme-ov-file#handling-non-serializable-options
  target: path.resolve(__dirname, './development'),
};

/**
 * The shared logger options, with `redaction` replacing known secrets and pattern matches in
 * every log line on top of the path-based `redact`.
 */
export const createLoggerOptions = (redaction: SecretRedactionOptions = {}): Params => ({
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
    hooks: {
      streamWrite: createSecretRedactor(redaction),
    },
    serializers: {
      err: sanitizePinoError,
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
});

export const defaultLoggerOptions = createLoggerOptions();

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

function sanitizePinoError(error: unknown): unknown {
  if (hasRawError(error)) {
    return sanitizeError(error.raw);
  }

  return sanitizeError(error);
}

function hasRawError(error: unknown): error is { raw: unknown } {
  return typeof error === 'object' && error !== null && 'raw' in error;
}
