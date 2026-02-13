import { Logger } from '@nestjs/common';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthMode } from '../../config/confluence.schema';
import { Redacted } from '../../utils/redacted';
import { OAuth2LoAuthStrategy } from './oauth2lo-auth.strategy';

vi.mock('@nestjs/common', async () => {
  const actual = await vi.importActual<typeof import('@nestjs/common')>('@nestjs/common');
  return { ...actual, Logger: vi.fn() };
});

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

  let fetchMock: ReturnType<typeof vi.fn>;
  let loggerLogMock: ReturnType<typeof vi.fn>;
  let loggerErrorMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-02-13T12:00:00.000Z'));

    loggerLogMock = vi.fn();
    loggerErrorMock = vi.fn();
    vi.mocked(Logger).mockImplementation(
      () =>
        ({
          log: loggerLogMock,
          error: loggerErrorMock,
        }) as unknown as Logger,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  describe('Cloud instance', () => {
    it('requests a Cloud access token via the Atlassian OAuth endpoint', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(successBody), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);
      await strategy.acquireToken();

      expect(fetchMock).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const [url, options] = fetchMock.mock.calls[0]!;
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

    it('returns accessToken and computed expiresAt for cloud', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(successBody), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);
      const result = await strategy.acquireToken();

      expect(result.accessToken).toBe('returned-access-token');
      expect(result.expiresAt).toEqual(new Date('2026-02-13T13:00:00.000Z'));
    });

    it('logs before acquiring token', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(successBody), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);
      await strategy.acquireToken();

      expect(loggerLogMock).toHaveBeenCalledWith(
        'Acquiring Confluence cloud token via OAuth 2.0 2LO',
      );
      expect(loggerErrorMock).not.toHaveBeenCalled();
    });
  });

  describe('Data Center instance', () => {
    it('requests a Data Center access token via the instance OAuth endpoint', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(successBody), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection);
      await strategy.acquireToken();

      expect(fetchMock).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const [url, options] = fetchMock.mock.calls[0]!;
      expect(url).toBe('https://confluence.corp.example.com/rest/oauth2/latest/token');
      expect(options.method).toBe('POST');
      expect(options.headers['Content-Type']).toBe('application/x-www-form-urlencoded');

      const params = new URLSearchParams(options.body);
      expect(params.get('grant_type')).toBe('client_credentials');
      expect(params.get('client_id')).toBe('my-client-id');
      expect(params.get('client_secret')).toBe('my-client-secret');
    });

    it('returns accessToken and computed expiresAt for DC', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(successBody), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection);
      const result = await strategy.acquireToken();

      expect(result.accessToken).toBe('returned-access-token');
      expect(result.expiresAt).toEqual(new Date('2026-02-13T13:00:00.000Z'));
    });
  });

  describe('error handling', () => {
    it('logs the error with sanitizeError before rethrowing', async () => {
      fetchMock.mockRejectedValueOnce(new Error('getaddrinfo ENOTFOUND'));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow();

      expect(loggerErrorMock).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const loggedPayload = loggerErrorMock.mock.calls[0]![0];
      expect(loggedPayload.msg).toBe('Failed to acquire Confluence cloud token via OAuth 2.0 2LO');
      expect(loggedPayload.error).toBeTypeOf('object');
      expect(loggedPayload.error).toHaveProperty('message');
    });

    it('throws on network error with endpoint URL', async () => {
      fetchMock.mockRejectedValueOnce(new Error('getaddrinfo ENOTFOUND'));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Network error requesting token from https://api.atlassian.com/oauth/token: getaddrinfo ENOTFOUND',
      );
    });

    it('throws on HTTP 401 indicating invalid credentials', async () => {
      fetchMock.mockResolvedValueOnce(new Response('Unauthorized', { status: 401 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Invalid credentials: https://api.atlassian.com/oauth/token responded with 401: Unauthorized',
      );
    });

    it('throws on HTTP 403 indicating invalid credentials', async () => {
      fetchMock.mockResolvedValueOnce(new Response('Forbidden', { status: 403 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, dcConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Invalid credentials: https://confluence.corp.example.com/rest/oauth2/latest/token responded with 403: Forbidden',
      );
    });

    it('throws on HTTP 500 with status and response body', async () => {
      fetchMock.mockResolvedValueOnce(new Response('Internal Server Error', { status: 500 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Token request to https://api.atlassian.com/oauth/token failed with status 500: Internal Server Error',
      );
    });

    it('throws on malformed response missing access_token', async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify({ expires_in: 3600 }), { status: 200 }),
      );

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /Malformed token response from https:\/\/api\.atlassian\.com\/oauth\/token:[\s\S]*access_token/,
      );
    });

    it('throws on malformed response missing expires_in', async () => {
      fetchMock.mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: 'tok' }), { status: 200 }),
      );

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /Malformed token response from https:\/\/api\.atlassian\.com\/oauth\/token:[\s\S]*expires_in/,
      );
    });

    it('throws on malformed response missing both fields', async () => {
      fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({}), { status: 200 }));

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        /Malformed token response from https:\/\/api\.atlassian\.com\/oauth\/token:[\s\S]*access_token[\s\S]*expires_in/,
      );
    });

    it('throws on non-JSON response body', async () => {
      fetchMock.mockResolvedValueOnce(
        new Response('not json', {
          status: 200,
          headers: { 'Content-Type': 'text/plain' },
        }),
      );

      const strategy = new OAuth2LoAuthStrategy(authConfig, cloudConnection);

      await expect(strategy.acquireToken()).rejects.toThrow(
        'Malformed response from https://api.atlassian.com/oauth/token: body is not valid JSON',
      );
    });
  });
});
