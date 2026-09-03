/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MockDrizzleDatabase, MockEncryptionService } from '../../__mocks__';

vi.mock('undici', () => ({
  fetch: vi.fn(),
}));

import { fetch } from 'undici';
import { TokenProvider } from '../token.provider';

const mockFetch = vi.mocked(fetch);
const mockDispatcher = { kind: 'proxy-dispatcher' } as unknown as Dispatcher;

describe('TokenProvider', () => {
  const mockConfig = {
    userProfileId: 'user-profile-123',
    clientId: 'test-client-id',
    clientSecret: 'test-client-secret',
    signInTenantId: 'common',
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
      };

      mockDependencies.drizzle.__nextQueryUserProfile = mockUserProfile;
      mockFetch.mockRejectedValue(new Error('Network error'));

      const unit = new TokenProvider(mockConfig, mockDependencies as any);

      await expect(unit.refreshAccessToken('user-profile-123')).rejects.toThrow(
        'Token refresh failed: Network error',
      );
    });
  });
});
