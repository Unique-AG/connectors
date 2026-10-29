import { IncomingMessage, ServerResponse } from 'node:http';
import { Socket } from 'node:net';
import pinoHttp from 'pino-http';
import { describe, expect, it } from 'vitest';
import {
  createSecretRedactor,
  MIN_SECRET_LENGTH,
  redactRequestSecrets,
  runWithLogSecrets,
  type SecretRedactionOptions,
} from './redact-secrets';

const mockApiKey = 'kyckr-api-key-0123456789';
const mockClientSecret = 'client"secret\\with-escapes';

function createCapturingLogger(redaction: SecretRedactionOptions = {}) {
  const lines: string[] = [];
  const { logger } = pinoHttp({
    hooks: { streamWrite: createSecretRedactor(redaction) },
    stream: { write: (line: string) => lines.push(line) },
  });
  return { logger, lines };
}

function parsedLines(lines: string[]): Record<string, unknown>[] {
  return lines.map((line) => JSON.parse(line));
}

describe('createSecretRedactor', () => {
  describe('known secrets', () => {
    it('redacts a secret in msg', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });

      logger.info(`calling upstream with ${mockApiKey}`);

      expect(parsedLines(lines)[0]?.msg).toBe('calling upstream with [Redacted]');
    });

    it('redacts a secret in err.message and err.stack', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });

      logger.error({ err: new Error(`Invalid key ${mockApiKey}`) }, 'request failed');

      const err = parsedLines(lines)[0]?.err as { message: string; stack: string };
      expect(err.message).toBe('Invalid key [Redacted]');
      expect(err.stack).toContain('Invalid key [Redacted]');
      expect(lines[0]).not.toContain(mockApiKey);
    });

    it('redacts a secret in a nested object', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });

      logger.info({ upstream: { request: { url: `https://api.test/v1?key=${mockApiKey}` } } });

      expect(parsedLines(lines)[0]?.upstream).toEqual({
        request: { url: 'https://api.test/v1?key=[Redacted]' },
      });
    });

    it('redacts every occurrence of a secret', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });

      logger.info(`${mockApiKey} then ${mockApiKey} again`);

      expect(parsedLines(lines)[0]?.msg).toBe('[Redacted] then [Redacted] again');
    });

    it('redacts a secret that JSON has to escape', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockClientSecret] });

      logger.info(`secret is ${mockClientSecret}`);

      expect(parsedLines(lines)[0]?.msg).toBe('secret is [Redacted]');
    });

    it('redacts the URL-encoded form of a secret', () => {
      const { logger, lines } = createCapturingLogger({ secrets: ['pa ss/word+123'] });

      logger.info(`GET /token?secret=${encodeURIComponent('pa ss/word+123')}&x=1`);

      expect(parsedLines(lines)[0]?.msg).toBe('GET /token?secret=[Redacted]&x=1');
    });

    it('prefers the longest secret when one contains another', () => {
      const { logger, lines } = createCapturingLogger({
        secrets: ['shared-prefix', 'shared-prefix-and-more'],
      });

      logger.info('value: shared-prefix-and-more');

      expect(parsedLines(lines)[0]?.msg).toBe('value: [Redacted]');
    });

    it(`skips secrets shorter than ${MIN_SECRET_LENGTH} characters`, () => {
      const { logger, lines } = createCapturingLogger({ secrets: ['', 'short'] });

      logger.info('a short message');

      expect(parsedLines(lines)[0]?.msg).toBe('a short message');
    });

    it('leaves the line unchanged when no secrets are registered', () => {
      const { logger, lines } = createCapturingLogger();

      logger.info({ upstream: 'reachable' }, 'all good');

      const line = parsedLines(lines)[0];
      expect(line?.msg).toBe('all good');
      expect(line?.upstream).toBe('reachable');
    });

    it('redacts a secret in an object key', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });

      logger.info({ cache: { [mockApiKey]: 'value' } });

      expect(lines[0]).not.toContain(mockApiKey);
      expect(parsedLines(lines)[0]?.cache).toEqual({ '[Redacted]': 'value' });
    });

    it('does not match object keys against the patterns', () => {
      const { logger, lines } = createCapturingLogger();

      logger.info({ 'password=hunter2': 'value' });

      expect(parsedLines(lines)[0]?.['password=hunter2']).toBe('value');
    });
  });

  describe('default patterns', () => {
    it.each([
      ['Authorization: Bearer abc.def-ghi', 'Authorization: Bearer [Redacted]'],
      ['Basic dXNlcjpwYXNz', 'Basic [Redacted]'],
      ['token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl', 'token [Redacted]'],
      ['x-api-key: 0123456789abcdef', 'x-api-key: [Redacted]'],
      ['GET /items?api_key=0123456789&page=2', 'GET /items?api_key=[Redacted]&page=2'],
      ['login with password=hunter2 failed', 'login with password=[Redacted] failed'],
      ['client_secret=abc123&grant_type=x', 'client_secret=[Redacted]&grant_type=x'],
      ['postgres://app:s3cret@db:5432/app', 'postgres://app:[Redacted]@db:5432/app'],
      ['key sk-abcdefghijklmnopqrstuvwxyz', 'key [Redacted]'],
      ['ghp_abcdefghijklmnopqrstuvwxyz0123456789', '[Redacted]'],
      ['aws AKIAABCDEFGHIJKLMNOP', 'aws [Redacted]'],
      ['-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----', '[Redacted]'],
    ])('redacts %j', (message, expected) => {
      const { logger, lines } = createCapturingLogger();

      logger.info(message);

      expect(parsedLines(lines)[0]?.msg).toBe(expected);
    });

    it('adds consumer patterns to the defaults', () => {
      const { logger, lines } = createCapturingLogger({
        patterns: [/tenant-key:(?<secret>\w+)/dg],
      });

      logger.info('tenant-key:abc123 and password=hunter2');

      expect(parsedLines(lines)[0]?.msg).toBe('tenant-key:[Redacted] and password=[Redacted]');
    });
  });

  describe('pattern validation', () => {
    it.each([
      [/password=\w+/, 'gd'],
      [/password=\w+/g, 'd'],
      [/password=\w+/d, 'g'],
    ])('rejects %s, which is missing the %s flag(s)', (pattern, missing) => {
      expect(() => createSecretRedactor({ patterns: [pattern] })).toThrow(
        `Secret pattern ${pattern} is missing the "${missing}" flag(s)`,
      );
    });
  });

  describe('opting out of the default patterns', () => {
    it('keeps only the consumer patterns and known secrets', () => {
      const { logger, lines } = createCapturingLogger({
        secrets: [mockApiKey],
        patterns: [/tenant-key:(?<secret>\w+)/dg],
        defaultPatterns: false,
      });

      logger.info(`password=hunter2 tenant-key:abc123 ${mockApiKey}`);

      expect(parsedLines(lines)[0]?.msg).toBe('password=hunter2 tenant-key:[Redacted] [Redacted]');
    });
  });

  describe('JSON structure', () => {
    it('keeps the line valid JSON when a pattern match runs into quotes and braces', () => {
      const { logger, lines } = createCapturingLogger();

      logger.info({ detail: 'Bearer abcdefgh12","level":99}' }, 'auth Bearer xyz12345"y\\z');

      const line = parsedLines(lines)[0];
      expect(line?.level).toBe(30);
      expect(line?.detail).toBe('Bearer [Redacted]","level":99}');
      expect(line?.msg).toBe('auth Bearer [Redacted]"y\\z');
    });

    it('keeps the line valid JSON when a consumer pattern matches whole values', () => {
      const { logger, lines } = createCapturingLogger({ patterns: [/[\s\S]+/dg] });

      logger.info({ nested: { list: ['a', 'b"c'] } }, 'everything');

      const line = parsedLines(lines)[0];
      expect(line?.msg).toBe('[Redacted]');
      expect(line?.nested).toEqual({ list: ['[Redacted]', '[Redacted]'] });
      expect(line?.level).toBe(30);
    });
  });

  describe('malformed input', () => {
    it('redacts a string value that is not valid JSON instead of throwing', () => {
      const redact = createSecretRedactor({ secrets: [mockApiKey] });

      const line = redact(`{"level":30,"msg":"bad \\x escape ${mockApiKey}","ok":"kept"}`);

      expect(JSON.parse(line)).toEqual({ level: 30, msg: '[Redacted]', ok: 'kept' });
    });
  });

  describe('request secrets', () => {
    it('redacts secrets registered for the current async context', async () => {
      const { logger, lines } = createCapturingLogger();

      await runWithLogSecrets(['user-token-abcdef'], async () => {
        await Promise.resolve();
        logger.info('upstream rejected user-token-abcdef');
      });
      logger.info('outside user-token-abcdef');

      expect(parsedLines(lines).map((line) => line.msg)).toEqual([
        'upstream rejected [Redacted]',
        'outside user-token-abcdef',
      ]);
    });

    it('keeps the outer secrets in a nested context', () => {
      const { logger, lines } = createCapturingLogger();

      runWithLogSecrets(['outer-secret-1'], () =>
        runWithLogSecrets(['inner-secret-2'], () => logger.info('outer-secret-1 inner-secret-2')),
      );

      expect(parsedLines(lines)[0]?.msg).toBe('[Redacted] [Redacted]');
    });

    it('redacts the secrets the consumer extracts from the request', () => {
      const { logger, lines } = createCapturingLogger();
      const mockRequest = new IncomingMessage(new Socket());
      mockRequest.headers = { 'x-tenant-token': 'opaque-token-1234', 'x-api-key': mockApiKey };
      const middleware = redactRequestSecrets((request) => [
        String(request.headers['x-tenant-token']),
        String(request.headers['x-api-key']),
      ]);

      middleware(mockRequest, new ServerResponse(mockRequest), () =>
        logger.info(`echoed opaque-token-1234 and ${mockApiKey}`),
      );
      logger.info('after the request opaque-token-1234');

      expect(parsedLines(lines).map((line) => line.msg)).toEqual([
        'echoed [Redacted] and [Redacted]',
        'after the request opaque-token-1234',
      ]);
    });

    it('serves and logs a request whose secrets cannot be read, naming the error', () => {
      const { logger, lines } = createCapturingLogger({ secrets: [mockApiKey] });
      const mockRequest = new IncomingMessage(new Socket());
      const middleware = redactRequestSecrets(() => {
        throw new TypeError(`no header for ${mockApiKey}`);
      });
      let served = false;

      middleware(mockRequest, new ServerResponse(mockRequest), () => {
        served = true;
        logger.info(`upstream rejected ${mockApiKey}`);
      });
      logger.info('after the request');

      expect(served).toBe(true);
      expect(lines[0]).not.toContain(mockApiKey);
      const [during, after] = parsedLines(lines);
      expect(during?.msg).toBe('upstream rejected [Redacted]');
      expect(during?.log_secrets_failed).toEqual({
        name: 'TypeError',
        stack: expect.arrayContaining([expect.stringMatching(/redact-secrets\.spec\.ts:\d+:\d+/)]),
      });
      expect(after).not.toHaveProperty('log_secrets_failed');
    });

    it('treats secrets that are not a list as unreadable', () => {
      const { logger, lines } = createCapturingLogger();
      const mockRequest = new IncomingMessage(new Socket());
      const middleware = redactRequestSecrets(() => undefined as unknown as string[]);

      middleware(mockRequest, new ServerResponse(mockRequest), () => logger.info('handled'));

      const line = parsedLines(lines)[0];
      expect(line?.msg).toBe('handled');
      expect(line?.log_secrets_failed).toMatchObject({ name: 'TypeError' });
    });
  });
});
