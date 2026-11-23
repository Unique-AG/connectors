import { type Mocked, TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it } from 'vitest';
import { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { sealSuccessor } from '../utils/successor-cipher';
import { OpaqueTokenService, type TokenPair } from './opaque-token.service';

describe('OpaqueTokenService', () => {
  let service: OpaqueTokenService;
  let store: Mocked<IOAuthStore>;
  let options: McpOAuthModuleOptions;

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
    const firstUsePair: TokenPair = {
      access_token: 'first-access',
      refresh_token: 'first-refresh',
      token_type: 'Bearer',
      expires_in: 3600,
      scope: 'read write',
    };

    it('stores the new pair, then redeems the refresh token with the sealed pair', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);
      store.redeemRefreshToken.mockResolvedValue(true);
      store.storeAccessToken.mockResolvedValue(undefined);
      store.storeRefreshToken.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('refresh-token', 'client-123');

      expect(result).toHaveProperty('access_token');
      expect(result).toHaveProperty('refresh_token');
      expect(store.redeemRefreshToken).toHaveBeenCalledWith('refresh-token', expect.any(String));
      expect(store.storeAccessToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ familyId: 'tkfam_123' }),
      );
      expect(store.storeRefreshToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ familyId: 'tkfam_123', generation: 2 }),
      );
      expect(store.removeAccessToken).not.toHaveBeenCalled();
      expect(store.removeRefreshToken).not.toHaveBeenCalled();
      expect(store.claimRefreshTokenReplay).not.toHaveBeenCalled();
    });

    it('revokes the token family when a used refresh token is replayed after the grace window', async () => {
      store.getRefreshToken.mockResolvedValue({
        ...mockRefreshMetadata,
        usedAt: new Date(Date.now() - 60_000),
      });
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('used-token', 'client-123');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
      expect(store.claimRefreshTokenReplay).not.toHaveBeenCalled();
      expect(store.redeemRefreshToken).not.toHaveBeenCalled();
      expect(store.storeRefreshToken).not.toHaveBeenCalled();
    });

    it('revokes the token family when a recently used token is presented by another client', async () => {
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('used-token', 'other-client');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
      expect(store.claimRefreshTokenReplay).not.toHaveBeenCalled();
    });

    it('serves the pair issued to the first use when a used token is replayed inside the grace window', async () => {
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });
      store.claimRefreshTokenReplay.mockResolvedValue(sealSuccessor('used-token', firstUsePair));

      const result = await service.refreshAccessToken('used-token', 'client-123');

      expect(result).toEqual(firstUsePair);
      expect(store.claimRefreshTokenReplay).toHaveBeenCalledWith('used-token', expect.any(Date));
      expect(store.revokeTokenFamily).not.toHaveBeenCalled();
      expect(store.redeemRefreshToken).not.toHaveBeenCalled();
      expect(store.storeRefreshToken).not.toHaveBeenCalled();
    });

    it('only accepts a replay of a token redeemed inside the grace window', async () => {
      const usedAt = new Date();
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt });
      store.claimRefreshTokenReplay.mockResolvedValue(sealSuccessor('used-token', firstUsePair));

      await service.refreshAccessToken('used-token', 'client-123');

      const [, usedAfter] = store.claimRefreshTokenReplay.mock.calls[0] ?? [];
      expect(usedAfter?.getTime()).toBeLessThanOrEqual(usedAt.getTime());
      expect(usedAfter?.getTime()).toBeGreaterThan(usedAt.getTime() - 11_000);
    });

    it('revokes the token family when a used token is replayed a second time', async () => {
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });
      store.claimRefreshTokenReplay.mockResolvedValue(undefined);
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('used-token', 'client-123');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
    });

    it('revokes the token family when the stored successor cannot be opened', async () => {
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });
      store.claimRefreshTokenReplay.mockResolvedValue(sealSuccessor('other-token', firstUsePair));
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('used-token', 'client-123');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
    });

    it('serves the pair the winner got and discards its own when a concurrent request redeemed the token first', async () => {
      store.getRefreshToken
        .mockResolvedValueOnce(mockRefreshMetadata)
        .mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });
      store.redeemRefreshToken.mockResolvedValue(false);
      store.claimRefreshTokenReplay.mockResolvedValue(sealSuccessor('refresh-token', firstUsePair));

      const result = await service.refreshAccessToken('refresh-token', 'client-123');

      expect(result).toEqual(firstUsePair);
      const [storedAccessToken] = store.storeAccessToken.mock.calls[0] ?? [];
      const [storedRefreshToken] = store.storeRefreshToken.mock.calls[0] ?? [];
      expect(store.removeAccessToken).toHaveBeenCalledWith(storedAccessToken);
      expect(store.removeRefreshToken).toHaveBeenCalledWith(storedRefreshToken);
      expect(store.revokeTokenFamily).not.toHaveBeenCalled();
    });

    it('revokes the token family when the concurrently redeemed token is gone', async () => {
      store.getRefreshToken
        .mockResolvedValueOnce(mockRefreshMetadata)
        .mockResolvedValueOnce(undefined);
      store.redeemRefreshToken.mockResolvedValue(false);
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('refresh-token', 'client-123');

      expect(result).toBeNull();
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
      expect(store.claimRefreshTokenReplay).not.toHaveBeenCalled();
    });

    it('revokes the new tokens when a concurrent request revoked the family before they were stored', async () => {
      store.getRefreshToken
        .mockResolvedValueOnce(mockRefreshMetadata)
        .mockResolvedValueOnce(undefined);
      store.redeemRefreshToken.mockResolvedValue(true);
      store.revokeTokenFamily.mockResolvedValue(undefined);

      const result = await service.refreshAccessToken('refresh-token', 'client-123');

      expect(result).toBeNull();
      expect(store.storeRefreshToken).toHaveBeenCalledWith(
        expect.any(String),
        expect.objectContaining({ familyId: 'tkfam_123' }),
      );
      expect(store.revokeTokenFamily).toHaveBeenCalledWith('tkfam_123');
    });

    it('rejects an expired refresh token without redeeming it', async () => {
      store.getRefreshToken.mockResolvedValue({
        ...mockRefreshMetadata,
        expiresAt: new Date(Date.now() - 1000),
      });

      const result = await service.refreshAccessToken('expired-token', 'client-123');

      expect(result).toBeNull();
      expect(store.removeRefreshToken).toHaveBeenCalledWith('expired-token');
      expect(store.redeemRefreshToken).not.toHaveBeenCalled();
    });

    it('validates client ownership before redeeming the token', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);

      const result = await service.refreshAccessToken('refresh-token', 'wrong-client');

      expect(result).toBeNull();
      expect(store.redeemRefreshToken).not.toHaveBeenCalled();
      expect(store.storeRefreshToken).not.toHaveBeenCalled();
      expect(store.removeRefreshToken).not.toHaveBeenCalled();
    });

    it('does not redeem the token when the requested scope exceeds the grant', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);

      const result = await service.refreshAccessToken('refresh-token', 'client-123', 'admin');

      expect(result).toBeNull();
      expect(store.redeemRefreshToken).not.toHaveBeenCalled();
      expect(store.storeRefreshToken).not.toHaveBeenCalled();
    });
  });

  describe('findRefreshTokenForRevocation', () => {
    it('returns a used refresh token so its family can still be revoked', async () => {
      const used = { ...mockRefreshMetadata, usedAt: new Date() };
      store.getRefreshToken.mockResolvedValue(used);

      await expect(service.findRefreshTokenForRevocation('used-token')).resolves.toEqual(used);
    });

    it('returns null for an unknown token', async () => {
      store.getRefreshToken.mockResolvedValue(undefined);

      await expect(service.findRefreshTokenForRevocation('missing')).resolves.toBeNull();
    });
  });

  describe('validateRefreshToken', () => {
    it('returns the metadata of an unused refresh token', async () => {
      store.getRefreshToken.mockResolvedValue(mockRefreshMetadata);

      const result = await service.validateRefreshToken('refresh-token');

      expect(result).toEqual(mockRefreshMetadata);
    });

    it('treats a used refresh token as invalid', async () => {
      store.getRefreshToken.mockResolvedValue({ ...mockRefreshMetadata, usedAt: new Date() });

      const result = await service.validateRefreshToken('used-token');

      expect(result).toBeNull();
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
