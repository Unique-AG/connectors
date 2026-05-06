import pinoHttp from 'pino-http';
import { describe, expect, it } from 'vitest';
import { defaultLoggerOptions } from './options';

describe('defaultLoggerOptions', () => {
  it('sanitizes pino-http wrapped GraphQL client errors', () => {
    const error = new Error(
      'Internal server error: {"response":{"errors":[]},"request":{"variables":{"input":{"title":"Secret Report.docx"}}}}',
    ) as Error & { response: Record<string, unknown>; request: Record<string, unknown> };
    error.response = {
      errors: [
        {
          message: 'Internal server error',
          path: ['contentUpsert'],
          extensions: { code: 'INTERNAL_SERVER_ERROR' },
        },
      ],
      status: 200,
    };
    error.request = { variables: { input: { title: 'Secret Report.docx' } } };

    const logLines: string[] = [];
    const pinoHttpOptions = defaultLoggerOptions.pinoHttp;
    if (
      typeof pinoHttpOptions !== 'object' ||
      pinoHttpOptions === null ||
      !('serializers' in pinoHttpOptions)
    ) {
      throw new Error('Expected pinoHttp options object');
    }

    const httpLogger = pinoHttp({
      serializers: pinoHttpOptions.serializers as Record<string, (value: unknown) => unknown>,
      stream: { write: (line) => logLines.push(line) },
    });

    httpLogger.logger.error({ err: error, msg: 'request failed' });

    const log = JSON.parse(logLines[0] ?? '{}') as {
      err?: {
        message?: string;
        graphqlErrors?: unknown;
        statusCode?: number;
      };
    };

    expect(log.err?.message).toBe('Internal server error');
    expect(log.err?.graphqlErrors).toEqual([
      {
        message: 'Internal server error',
        path: ['contentUpsert'],
        code: 'INTERNAL_SERVER_ERROR',
      },
    ]);
    expect(log.err?.statusCode).toBe(200);
    expect(JSON.stringify(log.err)).not.toContain('Secret Report.docx');
  });

  it('sanitizes pino-http raw-wrapped GraphQL client errors', () => {
    const error = new Error(
      'Internal server error: {"response":{"errors":[]},"request":{"variables":{"input":{"title":"Secret Report.docx"}}}}',
    ) as Error & { response: Record<string, unknown>; request: Record<string, unknown> };
    error.response = {
      errors: [
        {
          message: 'Internal server error',
          path: ['contentUpsert'],
          extensions: { code: 'INTERNAL_SERVER_ERROR' },
        },
      ],
      status: 200,
    };
    error.request = { variables: { input: { title: 'Secret Report.docx' } } };

    const logLines: string[] = [];
    const pinoHttpOptions = defaultLoggerOptions.pinoHttp;
    if (
      typeof pinoHttpOptions !== 'object' ||
      pinoHttpOptions === null ||
      !('serializers' in pinoHttpOptions)
    ) {
      throw new Error('Expected pinoHttp options object');
    }

    const httpLogger = pinoHttp({
      serializers: pinoHttpOptions.serializers as Record<string, (value: unknown) => unknown>,
      stream: { write: (line) => logLines.push(line) },
    });

    httpLogger.logger.error({ err: { raw: error }, msg: 'request failed' });

    const log = JSON.parse(logLines[0] ?? '{}') as {
      err?: {
        message?: string;
        graphqlErrors?: unknown;
        statusCode?: number;
      };
    };

    expect(log.err?.message).toBe('Internal server error');
    expect(log.err?.graphqlErrors).toEqual([
      {
        message: 'Internal server error',
        path: ['contentUpsert'],
        code: 'INTERNAL_SERVER_ERROR',
      },
    ]);
    expect(log.err?.statusCode).toBe(200);
    expect(JSON.stringify(log.err)).not.toContain('Secret Report.docx');
  });
});
