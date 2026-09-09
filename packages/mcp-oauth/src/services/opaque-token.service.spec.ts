import { type Mocked, TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { OpaqueTokenService } from './opaque-token.service';

describe('OpaqueTokenService', () => {
  let service: OpaqueTokenService;
  let store: Mocked<IOAuthStore>;
  let options: McpOAuthModuleOptions;

  beforeEach(async () => {
    options = {
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      authCodeExpiresIn: 600,
      hmacSecret: 'test-secret',
      serverUrl: 'http://localhost:3000',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      provider: {},
    } as McpOAuthModuleOptions;

    const { unit, unitRef } = await TestBed.solitary(OpaqueTokenService)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl(() => ({ ...options }))
      .compile();

    service = unit;
    store = unitRef.get(OAUTH_STORE_TOKEN);
  });

  describe('generateTokenPair', () => {
    it('creates access and refresh tokens with proper metadata', async () => {
      store.storeAccessToken.mockResolvedValue(undefined);
      store.storeRefreshToken.mockResolvedValue(undefined);

      const result = await service.generateTokenPair(
        'user-123',
        'client-123',
        'read write',
        'http://api.example.com',
        'profile-123',
      );

      expect(result).toHaveProperty('access_token');
      expect(result).toHaveProperty('refresh_token');
      expect(result.token_type).toBe('Bearer');
      expect(result.expires_in).toBe(3600);
      expect(result.scope).toBe('read write');

      expect(store.storeAccessToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          userId: 'user-123',
          clientId: 'client-123',
          scope: 'read write',
          resource: 'http://api.example.com',
          userProfileId: 'profile-123',
        }),
      );

      expect(store.storeRefreshToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          userId: 'user-123',
          clientId: 'client-123',
          familyId: expect.stringContaining('tkfam'),
          generation: 0,
        }),
      );
    });

    it('maintains token family across refreshes', async () => {
      store.storeAccessToken.mockResolvedValue(undefined);
      store.storeRefreshToken.mockResolvedValue(undefined);

      const familyId = 'tkfam_123';
      await service.generateTokenPair(
        'user-123',
        'client-123',
        'read',
        'http://api.example.com',
        'profile-123',
        familyId,
        2,
      );

      expect(store.storeRefreshToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          familyId,
          generation: 2,
        }),
      );
    });
  });

  describe('validateAccessToken', () => {
    const mockMetadata = {
      userId: 'user-123',
      clientId: 'client-123',
      scope: 'read write',
      resource: 'http://api.example.com',
      userProfileId: 'profile-123',
      expiresAt: new Date(Date.now() + 3600000),
    };

    it('validates unexpired access tokens', async () => {
      store.getAccessToken.mockResolvedValue(mockMetadata);

      const result = await service.validateAccessToken('valid-token');

      expect(result).toEqual({
        userId: 'user-123',
        clientId: 'client-123',
        scope: 'read write',
        resource: 'http://api.example.com',
        userProfileId: 'profile-123',
        userData: undefined,
      });
    });

    it('automatically removes expired tokens', async () => {
      const expiredMetadata = {
        ...mockMetadata,
        expiresAt: new Date(Date.now() - 1000),
      };
      store.getAccessToken.mockResolvedValue(expiredMetadata);
      store.removeAccessToken.mockResolvedValue(undefined);

      const result = await service.validateAccessToken('expired-token');

      expect(result).toBeNull();
      expect(store.removeAccessToken).toHaveBeenCalledWith('expired-token');
    });

    it('handles non-existent tokens gracefully', async () => {
      store.getAccessToken.mockResolvedValue(undefined);

      const result = await service.validateAccessToken('non-existent');

      expect(result).toBeNull();
    });
  });

  describe('refreshAccessToken', () => {
    const mockRefreshMetadata = {
      userId: 'user-123',
      clientId: 'client-123',
      scope: 'read write',
      resource: 'http://api.example.com',
      userProfileId: 'profile-123',
      familyId: 'tkfam_123',
      generation: 1,
      expiresAt: new Date(Date.now() + 86400000),
    };

    it('rotates refresh tokens with incremented generation', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);
      store.removeRefreshToken.mockResolvedValue(undefined);
      store.storeAccessToken.mockResolvedValue(undefined);
      store.storeRefreshToken.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('refresh-token', 'client-123');

      expect(result).toHaveProperty('access_token');
      expect(result).toHaveProperty('refresh_token');
      expect(store.removeRefreshToken).toHaveBeenCalledWith('refresh-token');
      expect(store.storeRefreshToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({
          familyId: 'tkfam_123',
          generation: 2,
        }),
      );
    });

    it('detects and prevents refresh token reuse attacks', async () => {
      store.isRefreshTokenUsed?.mockResolvedValue(true);
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);
      store.revokeTokenFamily?.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('used-token', 'client-123');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
    });

    it('validates client ownership before refresh', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);

      const result = await service.refreshAccessToken('refresh-token', 'wrong-client');

      expect(result).toBeNull();
      expect(store.removeRefreshToken).not.toHaveBeenCalled();
    });
  });

  describe('revokeAllTokensForUserProfile', () => {
    it('delegates to the store', async () => {
      store.revokeAllTokensForUserProfile?.mockResolvedValue({
        tokenCount: 4,
        clientIds: ['client-a', 'client-b'],
      });

      await service.revokeAllTokensForUserProfile('profile-123');

      expect(store.revokeAllTokensForUserProfile).toHaveBeenCalledWith('profile-123');
    });

    it('fails loudly when the store does not implement the optional method', async () => {
      store.revokeAllTokensForUserProfile = undefined;

      await expect(service.revokeAllTokensForUserProfile('profile-123')).rejects.toThrow(
        'The configured OAuth store cannot revoke every token for a user profile',
      );
    });
  });

  describe('revokeToken', () => {
    it('revokes access tokens', async () => {
      store.removeAccessToken.mockResolvedValue(undefined);

      const result = await service.revokeToken('access-token', 'access');

      expect(result).toBe(true);
      expect(store.removeAccessToken).toHaveBeenCalledWith('access-token');
    });

    it('revokes refresh tokens', async () => {
      store.removeRefreshToken.mockResolvedValue(undefined);

      const result = await service.revokeToken('refresh-token', 'refresh');

      expect(result).toBe(true);
      expect(store.removeRefreshToken).toHaveBeenCalledWith('refresh-token');
    });

    it('handles revocation failures gracefully', async () => {
      store.removeAccessToken.mockRejectedValue(new Error('Database error'));

      const result = await service.revokeToken('access-token', 'access');

      expect(result).toBe(false);
    });
  });

  describe('cleanupExpiredTokens', () => {
    it('cleans up tokens older than retention period', async () => {
      store.cleanupExpiredTokens?.mockResolvedValue(42);

      // biome-ignore lint/suspicious/noExplicitAny: Override private method to test cleanup
      const cleanup = (service as any).cleanupExpiredTokens.bind(service);
      await cleanup();

      expect(store.cleanupExpiredTokens).toHaveBeenCalledWith(7);
    });

    it('handles cleanup when store does not support it', async () => {
      store.cleanupExpiredTokens = undefined;

      // biome-ignore lint/suspicious/noExplicitAny: Override private method to test cleanup
      const cleanup = (service as any).cleanupExpiredTokens.bind(service);
      await expect(cleanup()).resolves.not.toThrow();
    });
  });
});
