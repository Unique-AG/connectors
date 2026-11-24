/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import assert from 'node:assert';
import { createLoggerOptions, runWithLogSecrets } from '@unique-ag/logger';
import { and, eq } from 'drizzle-orm';
import pino from 'pino';
import type { Dispatcher } from 'undici';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockDrizzleDatabase, MockEncryptionService } from '../../__mocks__';
import { userProfiles } from '../../db/schema';

vi.mock('undici', () => ({
  fetch: vi.fn(),
}));

import { fetch } from 'undici';
import { TokenProvider, TokenRefreshCoolingDownError } from '../token.provider';

const mockFetch = vi.mocked(fetch);
const mockDispatcher = { kind: 'proxy-dispatcher' } as unknown as Dispatcher;

const AADSTS7000215_BODY = {
  error: 'invalid_client',
  error_description:
    "AADSTS7000215: Invalid client secret provided. Ensure the secret being sent in the request is the client secret value, not the client secret ID, for a secret added to app 'ba326974-edcf-49ef-bf7a-74b3e0ea450a'.",
  error_codes: [7000215],
};

describe('TokenProvider', () => {
  const mockConfig = {
    userProfileId: 'user-profile-123',
    clientId: 'test-client-id',
    clientSecret: 'test-client-secret',
    signInTenantId: 'common',
    allowedTenantIds: [],
    scopes: ['https://graph.microsoft.com/.default'],
  };

  const mockDependencies = {
    drizzle: new MockDrizzleDatabase(),
    encryptionService: new MockEncryptionService(),
    dispatcher: mockDispatcher,
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('getAccessToken', () => {
    it('returns decrypted access token for valid user', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        accessToken: 'ZW5jcnlwdGVkLWFjY2Vzcy10b2tlbg==', // base64 encoded "encrypted-access-token"
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      const result = await unit.getAccessToken();

      expect(result).toBe('encrypted-access-token');
      expect(mockDependencies.drizzle.query.userProfiles.findFirst).toHaveBeenCalled();
    });

    it('throws error when user profile not found', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = undefined;

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.getAccessToken()).rejects.toThrow(
        'User profile not found: user-profile-123',
      );
    });

    it('throws error when access token not found', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        accessToken: null,
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.getAccessToken()).rejects.toThrow(
        'Access token not found for user: user-profile-123',
      );
    });
  });

  describe('refreshAccessToken', () => {
    it('successfully refreshes access token', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=', // base64 encoded "encrypted-refresh-token"
      };

      const mockTokenResponse = {
        access_token: 'new-access-token',
        refresh_token: 'new-refresh-token',
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue(mockTokenResponse),
      } as never);

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      const result = await unit.refreshAccessToken('user-profile-123');

      expect(result).toBe('new-access-token');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://login.microsoftonline.com/common/oauth2/v2.0/token',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: new URLSearchParams({
            grant_type: 'refresh_token',
            refresh_token: 'encrypted-refresh-token',
            client_id: 'test-client-id',
            client_secret: 'test-client-secret',
            scope: 'https://graph.microsoft.com/.default',
          }),
          dispatcher: mockDispatcher,
        },
      );

      expect(mockDependencies.drizzle.update).toHaveBeenCalled();
    });

    it('refreshes tokens against a pinned tenant endpoint', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
        }),
      } as never);

      const pinnedTenantId = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';
      const unit = new TokenProvider(
        { ...mockConfig, signInTenantId: pinnedTenantId },
        mockDependencies as any,
      );

      await unit.refreshAccessToken('user-profile-123');

      expect(mockFetch).toHaveBeenCalledWith(
        `https://login.microsoftonline.com/${pinnedTenantId}/oauth2/v2.0/token`,
        expect.objectContaining({ method: 'POST', dispatcher: mockDispatcher }),
      );
    });

    it('uses existing refresh token when new one not provided', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };

      const mockTokenResponse = {
        access_token: 'new-access-token',
        // No refresh_token in response
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue(mockTokenResponse),
      } as never);

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await unit.refreshAccessToken('user-profile-123');

      expect(mockDependencies.drizzle.update).toHaveBeenCalled();
    });

    it('throws error when user profile not found', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = undefined;

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'No refresh token available for user: user-profile-123',
      );
    });

    it('throws error when refresh token not found', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: null,
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'No refresh token available for user: user-profile-123',
      );
    });

    it('clears Graph tokens, revokes the MCP session, and throws on invalid_grant', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };
      const onPermanentAuthFailure = vi.fn().mockResolvedValue(undefined);

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;
      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        text: vi.fn().mockResolvedValue(
          JSON.stringify({
            error: 'invalid_grant',
            error_description: 'AADSTS50173: The provided grant has expired',
          }),
        ),
      } as never);

      const unit = new TokenProvider(mockConfig, {
        ...mockDependencies,
        onPermanentAuthFailure,
      } as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'AADSTS50173: The provided grant has expired',
      );
      expect(mockDependencies.drizzle.update).toHaveBeenCalled();
      expect(onPermanentAuthFailure).toHaveBeenCalledWith('user-profile-123');
    });

    it('clears Graph tokens and revokes the MCP session on invalid_client (AADSTS7000215)', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };
      const onPermanentAuthFailure = vi.fn().mockResolvedValue(undefined);

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;
      mockFetch.mockResolvedValue({
        ok: false,
        status: 401,
        statusText: 'Unauthorized',
        text: vi.fn().mockResolvedValue(JSON.stringify(AADSTS7000215_BODY)),
      } as never);

      const unit = new TokenProvider(mockConfig, {
        ...mockDependencies,
        onPermanentAuthFailure,
      } as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        AADSTS7000215_BODY.error_description,
      );
      expect(mockDependencies.drizzle.update).toHaveBeenCalled();
      expect(onPermanentAuthFailure).toHaveBeenCalledWith('user-profile-123');
    });

    it('throws error when token refresh fails', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
        tokenRefreshFailureCount: 0,
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        headers: new Headers(),
        text: vi.fn().mockResolvedValue('Invalid refresh token'),
      } as never);

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Bad Request',
      );
    });

    it('handles fetch errors gracefully', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
        tokenRefreshFailureCount: 0,
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;
      mockFetch.mockRejectedValue(new Error('Network error'));

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Network error',
      );
    });
  });

  describe('refreshAccessToken sharing', () => {
    const storedProfile = {
      id: 'user-profile-123',
      accessToken: Buffer.from('stored-access-token').toString('base64'),
      refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      tokenRefreshFailureCount: 0,
      tokenRefreshRetryAt: null,
    };

    beforeEach(() => {
      mockDependencies.drizzle.__nextQueryUserProfile = storedProfile;
      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ access_token: 'new-access-token' }),
      } as never);
    });

    it('calls Microsoft once for concurrent refreshes of the same user', async () => {
      const results = await Promise.all([
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
        ),
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
        ),
      ]);

      expect(results).toEqual(['new-access-token', 'new-access-token']);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('calls Microsoft again once the shared refresh has settled', async () => {
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await unit.refreshAccessToken('user-profile-123');
      await unit.refreshAccessToken('user-profile-123');

      expect(mockFetch).toHaveBeenCalledTimes(2);
    });

    it('reuses the stored access token when Graph rejected an older one', async () => {
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123', 'older-access-token')).resolves.toBe(
        'stored-access-token',
      );
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('refreshes for a request whose token is the stored one while another reuses it', async () => {
      const results = await Promise.all([
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
          'older-access-token',
        ),
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
          'stored-access-token',
        ),
      ]);

      expect(results).toEqual(['stored-access-token', 'new-access-token']);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('shares one refresh between requests that both rejected the stored token', async () => {
      const results = await Promise.all([
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
          'stored-access-token',
        ),
        new TokenProvider(mockConfig, mockDependencies as any).refreshAccessToken(
          'user-profile-123',
          'stored-access-token',
        ),
      ]);

      expect(results).toEqual(['new-access-token', 'new-access-token']);
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    it('refreshes when Graph rejected the stored access token', async () => {
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(
        unit.refreshAccessToken('user-profile-123', 'stored-access-token'),
      ).resolves.toBe('new-access-token');
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });
  });

  describe('refreshAccessToken backoff', () => {
    const now = new Date('2026-11-24T00:00:00.000Z');
    const minutesFromNow = (minutes: number) => new Date(now.getTime() + minutes * 60_000);

    const savedUpdates = () =>
      mockDependencies.drizzle.update.mock.results.map(
        (result) => result.value.set.mock.calls[0]?.[0],
      );

    const profileWithFailures = (
      tokenRefreshFailureCount: number,
      tokenRefreshRetryAt: Date | null = null,
    ) => ({
      id: 'user-profile-123',
      refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      tokenRefreshFailureCount,
      tokenRefreshRetryAt,
    });

    const failedResponse = (status: number, body: unknown, headers: HeadersInit = {}) =>
      ({
        ok: false,
        status,
        statusText: 'Failed',
        headers: new Headers(headers),
        text: vi.fn().mockResolvedValue(JSON.stringify(body)),
      }) as never;

    const connectTimeout = () =>
      Object.assign(new TypeError('fetch failed'), {
        cause: { code: 'UND_ERR_CONNECT_TIMEOUT' },
      });

    beforeEach(() => {
      vi.useFakeTimers({ now, toFake: ['Date'] });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('skips Microsoft while a previous failure is backing off', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(1, minutesFromNow(1));
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toBeInstanceOf(
        TokenRefreshCoolingDownError,
      );
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('calls Microsoft once the backoff has passed', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(1, minutesFromNow(-1));
      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ access_token: 'new-access-token' }),
      } as never);
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).resolves.toBe('new-access-token');
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailedAt: null,
          tokenRefreshFailureCount: 0,
          tokenRefreshFailureCode: null,
          tokenRefreshRetryAt: null,
        }),
      ]);
    });

    it('backs off one minute after a first network failure', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockRejectedValue(connectTimeout());
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: fetch failed',
      );
      expect(savedUpdates()).toEqual([
        {
          tokenRefreshFailedAt: now,
          tokenRefreshFailureCount: 1,
          tokenRefreshFailureCode: 'network_UND_ERR_CONNECT_TIMEOUT',
          tokenRefreshRetryAt: minutesFromNow(1),
        },
      ]);
    });

    it('doubles the backoff with each consecutive failure', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(3);
      mockFetch.mockResolvedValue(failedResponse(503, { error: 'temporarily_unavailable' }));
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Failed',
      );
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailureCount: 4,
          tokenRefreshFailureCode: 'http_503_temporarily_unavailable',
          tokenRefreshRetryAt: minutesFromNow(8),
        }),
      ]);
    });

    it('caps the backoff at 30 minutes', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(9);
      mockFetch.mockResolvedValue(failedResponse(500, {}));
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailureCode: 'http_500',
          tokenRefreshRetryAt: minutesFromNow(30),
        }),
      ]);
    });

    it('waits as long as the Retry-After header asks', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue(failedResponse(429, {}, { 'Retry-After': '300' }));
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailureCode: 'http_429',
          tokenRefreshRetryAt: minutesFromNow(5),
        }),
      ]);
    });

    it('waits until a Retry-After given as an HTTP date', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue(
        failedResponse(503, {}, { 'Retry-After': minutesFromNow(5).toUTCString() }),
      );
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).toEqual([
        expect.objectContaining({ tokenRefreshRetryAt: minutesFromNow(5) }),
      ]);
    });

    it('waits a Retry-After longer than 30 minutes in full', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue(failedResponse(503, {}, { 'Retry-After': '3600' }));
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).toEqual([
        expect.objectContaining({ tokenRefreshRetryAt: minutesFromNow(60) }),
      ]);
    });

    it('backs off when the error body cannot be read, keeping its Retry-After', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue({
        ok: false,
        status: 429,
        statusText: 'Too Many Requests',
        headers: new Headers({ 'Retry-After': '300' }),
        text: vi.fn().mockRejectedValue(new TypeError('terminated')),
      } as never);
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Too Many Requests',
      );
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailureCode: 'http_429_unreadable_body',
          tokenRefreshRetryAt: minutesFromNow(5),
        }),
      ]);
    });

    it('backs off when the token body cannot be read', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue({
        ok: true,
        status: 200,
        statusText: 'OK',
        headers: new Headers(),
        json: vi.fn().mockRejectedValue(new TypeError('terminated')),
      } as never);
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).toEqual([
        expect.objectContaining({
          tokenRefreshFailureCode: 'http_200_unreadable_body',
          tokenRefreshRetryAt: minutesFromNow(1),
        }),
      ]);
    });

    it('records the failure only on the grant it tried to refresh', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockRejectedValue(connectTimeout());
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      const [update] = mockDependencies.drizzle.update.mock.results;
      expect(update?.value.where).toHaveBeenCalledWith(
        and(
          eq(userProfiles.id, 'user-profile-123'),
          eq(userProfiles.refreshToken, 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4='),
        ),
      );
    });

    it("logs Microsoft's error code but not its description or trace ids", async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockResolvedValue(
        failedResponse(400, {
          error: 'invalid_scope',
          error_description: 'AADSTS70011: scope is invalid for app 11111111-2222',
          error_codes: [70011],
          trace_id: 'trace-id-value',
          correlation_id: 'correlation-id-value',
        }),
      );
      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();

      // Private logger: the global test setup mocks Nest's Logger per instance.
      const errorLog = (unit as any).logger.error;
      const logged = JSON.stringify(errorLog.mock.calls);
      expect(errorLog).toHaveBeenCalledWith(
        expect.objectContaining({ failureCode: 'http_400_invalid_scope', aadstsCodes: [70011] }),
      );
      expect(logged).not.toContain('AADSTS70011:');
      expect(logged).not.toContain('trace-id-value');
      expect(logged).not.toContain('correlation-id-value');
    });

    it('keeps the tokens and the MCP session on a transient failure', async () => {
      const onPermanentAuthFailure = vi.fn();
      mockDependencies.drizzle.__nextQueryUserProfile = profileWithFailures(0);
      mockFetch.mockRejectedValue(connectTimeout());
      const unit = new TokenProvider(mockConfig, {
        ...mockDependencies,
        onPermanentAuthFailure,
      } as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow();
      expect(savedUpdates()).not.toContainEqual(expect.objectContaining({ accessToken: null }));
      expect(onPermanentAuthFailure).not.toHaveBeenCalled();
    });
  });

  describe('refreshAccessToken with a tenant allowlist', () => {
    const LISTED_TENANT = 'd050ee55-f842-4802-8263-d802dc017162';
    const OTHER_TENANT = '79a9ddfe-a4f3-4307-8086-471132901889';

    const entraAccessToken = (tid: string) =>
      `eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.${Buffer.from(JSON.stringify({ tid })).toString('base64url')}.signature`;

    const savedTokens = () =>
      mockDependencies.drizzle.update.mock.results.map(
        (result) => result.value.set.mock.calls[0]?.[0],
      );

    beforeEach(() => {
      mockDependencies.drizzle.__nextQueryUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };
    });

    it('stores the refreshed token of a listed tenant', async () => {
      const accessToken = entraAccessToken(LISTED_TENANT);
      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ access_token: accessToken }),
      } as never);

      const unit = new TokenProvider(
        { ...mockConfig, allowedTenantIds: [LISTED_TENANT] },
        mockDependencies as any,
      );

      await expect(unit.refreshAccessToken('user-profile-123')).resolves.toBe(accessToken);
      expect(savedTokens()).toEqual([expect.objectContaining({ accessToken: expect.any(String) })]);
    });

    it('clears the Graph tokens and revokes the MCP session of a tenant no longer listed', async () => {
      const onPermanentAuthFailure = vi.fn().mockResolvedValue(undefined);
      mockFetch.mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ access_token: entraAccessToken(OTHER_TENANT) }),
      } as never);

      const unit = new TokenProvider({ ...mockConfig, allowedTenantIds: [LISTED_TENANT] }, {
        ...mockDependencies,
        onPermanentAuthFailure,
      } as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        `Entra tenant ${OTHER_TENANT} is not on the allowlist`,
      );
      expect(savedTokens()).toEqual([{ accessToken: null, refreshToken: null }]);
      expect(onPermanentAuthFailure).toHaveBeenCalledWith('user-profile-123');
    });
  });

  describe('log redaction', () => {
    function createCapturingLogger() {
      const pinoHttpOptions = createLoggerOptions().pinoHttp;
      assert.ok(
        typeof pinoHttpOptions === 'object' &&
          pinoHttpOptions !== null &&
          'hooks' in pinoHttpOptions,
        'Expected pinoHttp options with hooks',
      );
      const lines: string[] = [];
      const logger = pino({ hooks: pinoHttpOptions.hooks }, { write: (line) => lines.push(line) });
      return { logger, lines };
    }

    it('redacts the access token from what the request logs after reading it', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = {
        id: 'user-profile-123',
        accessToken: 'ZW5jcnlwdGVkLWFjY2Vzcy10b2tlbg==',
      };
      const unit = new TokenProvider(mockConfig, mockDependencies as any);
      const { logger, lines } = createCapturingLogger();

      await runWithLogSecrets([], async () => {
        const accessToken = await unit.getAccessToken();
        logger.error(`Graph rejected ${accessToken}`);
      });

      expect(JSON.parse(lines[0] ?? '{}').msg).toBe('Graph rejected [Redacted]');
    });

    it('redacts the old and new tokens from what the request logs after a refresh', async () => {
      mockDependencies.drizzle.__nextQueryUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
        }),
      } as any);
      const unit = new TokenProvider(mockConfig, mockDependencies as any);
      const { logger, lines } = createCapturingLogger();

      await runWithLogSecrets([], async () => {
        await unit.refreshAccessToken('user-profile-123');
        logger.error('tokens encrypted-refresh-token new-access-token new-refresh-token');
      });

      expect(JSON.parse(lines[0] ?? '{}').msg).toBe('tokens [Redacted] [Redacted] [Redacted]');
    });
  });
});
