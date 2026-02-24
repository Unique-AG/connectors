import type pino from 'pino';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthMode } from '../../../../config/confluence.schema';
import { Redacted } from '../../../../utils/redacted';
import { OAuth2LoAuthStrategy } from '../oauth2lo-auth.strategy';

const { mockRequest } = vi.hoisted(() => ({
  mockRequest: vi.fn(),
}));

vi.mock('undici', () => ({
  request: mockRequest,
}));

describe('OAuth2LoAuthStrategy', () => {
  const authConfig = {
    mode: AuthMode.OAUTH_2LO,
    clientId: 'my-client-id',
    clientSecret: new Redacted('my-client-secret'),
  };

  const cloudConnection = {
    instanceType: 'cloud' as const,
    baseUrl: 'https://my-site.atlassian.net',
  };

  const dcConnection = {
    instanceType: 'data-center' as const,
    baseUrl: 'https://confluence.corp.example.com',
  };

  const successBody = {
    access_token: 'returned-access-token',
    expires_in: 3600,
    token_type: 'Bearer',
  };

  let loggerInfoMock: ReturnType<typeof vi.fn>;
  let loggerErrorMock: ReturnType<typeof vi.fn>;
  let mockLogger: pino.Logger;

  function mockTokenResponse(statusCode: number, body: unknown): void {
    mockRequest.mockResolvedValueOnce({
      statusCode,
      body: {
        json: vi.fn().mockResolvedValue(body),
        text: vi.fn().mockResolvedValue(typeof body === 'string' ? body : JSON.stringify(body)),
      },
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-02-13T12:00:00.000Z'));

    loggerInfoMock = vi.fn();
    loggerErrorMock = vi.fn();
    mockLogger = {
      info: loggerInfoMock,
      error: loggerErrorMock,
    } as unknown as pino.Logger;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('Cloud instance', () => {
    it('requests a Cloud access token via the Atlassian OAuth endpoint', async () => {
      mockTokenResponse(200, successBody);

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);
      await strategy.acquireToken();

      expect(mockRequest).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const [url, options] = mockRequest.mock.calls[0]!;
      expect(url).toBe('https://api.atlassian.com/oauth/token');
      expect(options.method).toBe('POST');
      expect(options.headers['Content-Type']).toBe('application/json');

      const body = JSON.parse(options.body);
      expect(body).toEqual({
        grant_type: 'client_credentials',
        client_id: 'my-client-id',
        client_secret: 'my-client-secret',
      });
    });

    it('returns access token for cloud', async () => {
      mockTokenResponse(200, successBody);

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);
      const token = await strategy.acquireToken();

      expect(token).toBe('returned-access-token');
    });

    it('caches token across sequential calls', async () => {
      mockTokenResponse(200, successBody);
      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      const tokenA = await strategy.acquireToken();
      const tokenB = await strategy.acquireToken();

      expect(tokenA).toBe('returned-access-token');
      expect(tokenB).toBe('returned-access-token');
      expect(mockRequest).toHaveBeenCalledOnce();
    });

    it('deduplicates concurrent token acquisition calls', async () => {
      mockTokenResponse(200, successBody);
      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      const [tokenA, tokenB] = await Promise.all([
        strategy.acquireToken(),
        strategy.acquireToken(),
      ]);

      expect(tokenA).toBe('returned-access-token');
      expect(tokenB).toBe('returned-access-token');
      expect(mockRequest).toHaveBeenCalledOnce();
    });

    it('logs before acquiring token', async () => {
      mockTokenResponse(200, successBody);

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);
      await strategy.acquireToken();

      expect(loggerInfoMock).toHaveBeenCalledWith(
        'Acquiring Confluence cloud token via OAuth 2.0 2LO',
      );
      expect(loggerErrorMock).not.toHaveBeenCalled();
    });
  });

  describe('Data Center instance', () => {
    it('requests a Data Center access token via the instance OAuth endpoint', async () => {
      mockTokenResponse(200, successBody);

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection, mockLogger);
      await strategy.acquireToken();

      expect(mockRequest).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const [url, options] = mockRequest.mock.calls[0]!;
      expect(url).toBe('https://confluence.corp.example.com/rest/oauth2/latest/token');
      expect(options.method).toBe('POST');
      expect(options.headers['Content-Type']).toBe('application/x-www-form-urlencoded');

      const params = new URLSearchParams(options.body);
      expect(params.get('grant_type')).toBe('client_credentials');
      expect(params.get('client_id')).toBe('my-client-id');
      expect(params.get('client_secret')).toBe('my-client-secret');
      expect(params.get('scope')).toBe('READ');
    });

    it('returns access token for DC', async () => {
      mockTokenResponse(200, successBody);

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection, mockLogger);
      const token = await strategy.acquireToken();

      expect(token).toBe('returned-access-token');
    });
  });

  describe('error handling', () => {
    it('logs the error with sanitizeError before rethrowing', async () => {
      mockRequest.mockRejectedValueOnce(new Error('getaddrinfo ENOTFOUND'));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow();

      expect(loggerErrorMock).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const loggedPayload = loggerErrorMock.mock.calls[0]![0];
      expect(loggedPayload.msg).toBe('Failed to acquire Confluence cloud token via OAuth 2.0 2LO');
      expect(loggedPayload.error).toBeTypeOf('object');
      expect(loggedPayload.error).toHaveProperty('message');
    });

    it('throws the original network error', async () => {
      const networkError = new Error('getaddrinfo ENOTFOUND');
      mockRequest.mockRejectedValueOnce(networkError);

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(networkError);
    });

    it('throws on HTTP 401 indicating invalid credentials', async () => {
      mockTokenResponse(401, 'Unauthorized');

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Error response from https://api.atlassian.com/oauth/token: 401 Unauthorized',
      );
    });

    it('throws on HTTP 403 indicating invalid credentials', async () => {
      mockTokenResponse(403, 'Forbidden');

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Error response from https://confluence.corp.example.com/rest/oauth2/latest/token: 403 Forbidden',
      );
    });

    it('throws on HTTP 500 with status and response body', async () => {
      mockTokenResponse(500, 'Internal Server Error');

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Error response from https://api.atlassian.com/oauth/token: 500 Internal Server Error',
      );
    });

    it('falls back to an unreadable-body message when response text cannot be read', async () => {
      mockRequest.mockResolvedValueOnce({
        statusCode: 500,
        body: {
          json: vi.fn(),
          text: vi.fn().mockRejectedValue(new Error('stream already disturbed')),
        },
      });

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Error response from https://api.atlassian.com/oauth/token: 500 No response body',
      );
    });

    it('throws ZodError on malformed response missing access_token', async () => {
      mockTokenResponse(200, { expires_in: 3600 });

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /access_token/,
      );
    });

    it('throws ZodError on malformed response missing expires_in', async () => {
      mockTokenResponse(200, { access_token: 'tok' });

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /expires_in/,
      );
    });

    it('throws ZodError on malformed response missing both fields', async () => {
      mockTokenResponse(200, {});

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /access_token/,
      );
    });

    it('throws on non-JSON response body', async () => {
      mockRequest.mockResolvedValueOnce({
        statusCode: 200,
        body: {
          json: vi.fn().mockRejectedValue(new Error('invalid json')),
          text: vi.fn().mockResolvedValue('not json'),
        },
      });

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection, mockLogger);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'invalid json',
      );
    });
  });
});
