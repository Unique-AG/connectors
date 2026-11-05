import assert from 'node:assert';
import pinoHttp from 'pino-http';
import { describe, expect, it } from 'vitest';
import { createLoggerOptions, defaultLoggerOptions } from './options';

function createHttpLogger() {
  const pinoHttpOptions = defaultLoggerOptions.pinoHttp;
  assert.ok(
    typeof pinoHttpOptions === 'object' &&
      pinoHttpOptions !== null &&
      'serializers' in pinoHttpOptions,
    'Expected pinoHttp options object',
  );

  const logLines: string[] = [];
  const { logger } = pinoHttp({
    redact: pinoHttpOptions.redact,
    serializers: pinoHttpOptions.serializers as Record<string, (value: unknown) => unknown>,
    stream: { write: (line) => logLines.push(line) },
  });
  return { logger, logLines };
}

function createMockRequest(originalUrl: string, query: Record<string, string>) {
  return {
    id: 42,
    method: 'GET',
    url: originalUrl,
    originalUrl,
    query,
    params: {},
    headers: {
      cookie: 'session=secret-cookie',
      authorization: 'Bearer secret-token',
      host: 'mcp.test',
    },
    socket: { remoteAddress: '10.0.0.7', remotePort: 51234 },
  };
}

interface RequestLog {
  req?: Record<string, unknown> & { headers?: Record<string, unknown> };
}

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

    const { logger, logLines } = createHttpLogger();

    logger.error({ err: error, msg: 'request failed' });

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

    const { logger, logLines } = createHttpLogger();

    logger.error({ err: { raw: error }, msg: 'request failed' });

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

  describe('req serializer', () => {
    it('strips the query string and parsed query from /auth/ requests', () => {
      const { logger, logLines } = createHttpLogger();

      logger.info({
        req: createMockRequest('/auth/callback?code=secret-code&state=secret-state', {
          code: 'secret-code',
          state: 'secret-state',
        }),
      });

      const log = JSON.parse(logLines[0] ?? '{}') as RequestLog;
      expect(log.req?.url).toBe('/auth/callback');
      expect(log.req).not.toHaveProperty('query');
      expect(logLines[0]).not.toContain('secret-code');
      expect(logLines[0]).not.toContain('secret-state');
    });

    it('keeps the query of requests outside /auth/', () => {
      const { logger, logLines } = createHttpLogger();

      logger.info({ req: createMockRequest('/mcp?page=2', { page: '2' }) });

      const log = JSON.parse(logLines[0] ?? '{}') as RequestLog;
      expect(log.req?.url).toBe('/mcp?page=2');
      expect(log.req?.query).toEqual({ page: '2' });
    });

    it('keeps the request id and remote address', () => {
      const { logger, logLines } = createHttpLogger();

      logger.info({
        req: createMockRequest('/auth/callback?code=secret-code', { code: 'secret-code' }),
      });

      const log = JSON.parse(logLines[0] ?? '{}') as RequestLog;
      expect(log.req).toMatchObject({
        id: 42,
        method: 'GET',
        remoteAddress: '10.0.0.7',
        remotePort: 51234,
      });
    });

    it('redacts the cookie and authorization headers', () => {
      const { logger, logLines } = createHttpLogger();

      logger.info({ req: createMockRequest('/auth/callback', {}) });

      const log = JSON.parse(logLines[0] ?? '{}') as RequestLog;
      expect(log.req?.headers).toEqual({
        cookie: '[Redacted]',
        authorization: '[Redacted]',
        host: 'mcp.test',
      });
    });
  });

  it('redacts the secrets passed to createLoggerOptions from every line', () => {
    const pinoHttpOptions = createLoggerOptions({ secrets: ['env-client-secret'] }).pinoHttp;
    assert.ok(
      typeof pinoHttpOptions === 'object' && pinoHttpOptions !== null && 'hooks' in pinoHttpOptions,
      'Expected pinoHttp options with hooks',
    );
    const logLines: string[] = [];
    const httpLogger = pinoHttp({
      hooks: pinoHttpOptions.hooks,
      stream: { write: (line) => logLines.push(line) },
    });

    httpLogger.logger.error(
      { err: new Error('rejected env-client-secret') },
      'token exchange failed',
    );

    expect(logLines[0]).not.toContain('env-client-secret');
    expect(JSON.parse(logLines[0] ?? '{}').err.message).toBe('rejected [Redacted]');
  });
});
