/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import assert from 'node:assert';
import { createLoggerOptions, runWithLogSecrets } from '@unique-ag/logger';
import pino from 'pino';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MockDrizzleDatabase, MockEncryptionService } from '../__mocks__';
import { TokenProvider } from './token.provider';

// Mock fetch globally
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

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
      });

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
      });

      const pinnedTenantId = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';
      const unit = new TokenProvider(
        { ...mockConfig, signInTenantId: pinnedTenantId },
        mockDependencies as any,
      );

      await unit.refreshAccessToken('user-profile-123');

      expect(mockFetch).toHaveBeenCalledWith(
        `https://login.microsoftonline.com/${pinnedTenantId}/oauth2/v2.0/token`,
        expect.objectContaining({ method: 'POST' }),
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
      });

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
      });

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

    it('throws error when token refresh fails', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;

      mockFetch.mockResolvedValue({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        text: vi.fn().mockResolvedValue('Invalid refresh token'),
      });

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Bad Request',
      );
    });

    it('handles fetch errors gracefully', async () => {
      const mockUserProfile = {
        id: 'user-profile-123',
        refreshToken: 'ZW5jcnlwdGVkLXJlZnJlc2gtdG9rZW4=',
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;
      mockFetch.mockRejectedValue(new Error('Network error'));

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Network error',
      );
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
      });

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
      });

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
        json: vi.fn().mockResolvedValue({
          access_token: 'new-access-token',
          refresh_token: 'new-refresh-token',
        }),
      });
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
