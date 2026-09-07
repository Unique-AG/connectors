import { createHmac } from 'node:crypto';
import { UnauthorizedException } from '@nestjs/common';
import { type Mocked, TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { ClientService } from './client.service';
import { McpOAuthService } from './mcp-oauth.service';
import { PassportUser } from './oauth-strategy.service';
import { OpaqueTokenService } from './opaque-token.service';

describe('McpOAuthService', () => {
  let service: McpOAuthService;
  let store: Mocked<IOAuthStore>;
  let tokenService: Mocked<OpaqueTokenService>;
  let clientService: Mocked<ClientService>;
  let options: McpOAuthModuleOptions;
  let validHmac: string;

  beforeEach(async () => {
    options = {
      hmacSecret: 'test-secret',
      authCodeExpiresIn: 600,
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      serverUrl: 'http://localhost:3000',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      provider: {},
    } as McpOAuthModuleOptions;

    const { unit, unitRef } = await TestBed.solitary(McpOAuthService)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl(() => ({ ...options }))
      .compile();

    service = unit;
    store = unitRef.get(OAUTH_STORE_TOKEN);
    tokenService = unitRef.get(OpaqueTokenService);
    clientService = unitRef.get(ClientService);

    validHmac = createHmac('sha256', options.hmacSecret)
      .update('session-123:nonce-123')
      .digest('base64url');
  });

  describe('processAuthenticationSuccess', () => {
    const mockUser: PassportUser = {
      profile: {
        id: 'user-123',
        username: 'testuser',
        displayName: 'Test User',
        email: 'test@example.com',
      },
      accessToken: 'provider-access-token',
      refreshToken: 'provider-refresh-token',
      provider: 'test-provider',
    };

    const mockSession = {
      sessionId: 'session-123',
      clientId: 'client-123',
      redirectUri: 'http://localhost:3000/callback',
      codeChallenge: 'challenge',
      codeChallengeMethod: 'S256',
      state: undefined,
      oauthState: 'oauth-state',
      resource: 'http://api.example.com',
      scope: 'read write',
      expiresAt: Date.now() + 600000,
    };

    it('generates authorization code and redirects on successful authentication', async () => {
      store.getOAuthSession.mockResolvedValue({ ...mockSession, state: validHmac });
      store.upsertUserProfile.mockResolvedValue('profile-123');
      store.storeAuthCode.mockResolvedValue(undefined);
      store.removeOAuthSession.mockResolvedValue(undefined);

      const result = await service.processAuthenticationSuccess({
        user: mockUser,
        sessionId: 'session-123',
        sessionNonce: 'nonce-123',
        sessionHmac: validHmac,
      });

      expect(result.redirectUrl).toContain('http://localhost:3000/callback');
      expect(result.redirectUrl).toContain('code=');
      expect(result.redirectUrl).toContain('state=oauth-state');
      expect(store.storeAuthCode).toHaveBeenCalled();
      expect(store.removeOAuthSession).toHaveBeenCalledWith('session-123');
    });

    it('saves the user profile', async () => {
      store.getOAuthSession.mockResolvedValue({ ...mockSession, state: validHmac });
      await service.processAuthenticationSuccess({
        user: mockUser,
        sessionId: 'session-123',
        sessionNonce: 'nonce-123',
        sessionHmac: validHmac,
      });

      expect(store.upsertUserProfile).toHaveBeenCalledWith(mockUser);
    });

    it('throws UnauthorizedException when session is not found', async () => {
      store.getOAuthSession.mockResolvedValue(undefined);

      await expect(
        service.processAuthenticationSuccess({
          user: mockUser,
          sessionId: 'invalid-session',
          sessionNonce: 'nonce',
          sessionHmac: 'hmac',
        }),
      ).rejects.toThrow(UnauthorizedException);
    });

    it('validates HMAC to prevent session hijacking', async () => {
      store.getOAuthSession.mockResolvedValue({ ...mockSession, state: validHmac });

      await expect(
        service.processAuthenticationSuccess({
          user: mockUser,
          sessionId: 'session-123',
          sessionNonce: 'nonce',
          sessionHmac: 'invalid-hmac',
        }),
      ).rejects.toThrow('Invalid state.');
    });
  });

  describe('exchangeAuthorizationCodeForToken', () => {
    const tokenDto = {
      grant_type: 'authorization_code',
      code: 'auth-code-123',
      client_id: 'client-123',
      client_secret: 'client-secret',
      code_verifier: 'verifier',
      redirect_uri: 'http://localhost:3000/callback',
      resource: 'http://api.example.com',
      audience: 'http://api.example.com',
    };

    const mockAuthCode = {
      code: 'auth-code-123',
      user_id: 'user-123',
      client_id: 'client-123',
      redirect_uri: 'http://localhost:3000/callback',
      code_challenge: 'challenge',
      code_challenge_method: 'S256',
      expires_at: Date.now() + 600000,
      resource: 'http://api.example.com',
      scope: 'read write',
      user_profile_id: 'profile-123',
    };

    it('exchanges valid authorization code for tokens', async () => {
      store.getAuthCode.mockResolvedValue(mockAuthCode);
      store.removeAuthCode.mockResolvedValue(undefined);
      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.generateTokenPair.mockResolvedValue({
        access_token: 'access-token',
        refresh_token: 'refresh-token',
        token_type: 'Bearer',
        expires_in: 3600,
        scope: 'read write',
      });

      // biome-ignore lint/suspicious/noExplicitAny: Mock override private method
      vi.spyOn(service as any, 'validatePKCE').mockReturnValue(true);

      const result = await service.exchangeAuthorizationCodeForToken(tokenDto);

      expect(result).toHaveProperty('access_token');
      expect(result).toHaveProperty('refresh_token');
      expect(store.removeAuthCode).toHaveBeenCalledWith('auth-code-123');
      expect(tokenService.generateTokenPair).toHaveBeenCalled();
    });

    it('prevents authorization code replay attacks', async () => {
      store.getAuthCode.mockResolvedValue(undefined);

      await expect(service.exchangeAuthorizationCodeForToken(tokenDto)).rejects.toThrow(
        'Invalid or expired authorization code',
      );
    });

    it('validates client credentials before issuing tokens', async () => {
      store.getAuthCode.mockResolvedValue(mockAuthCode);
      store.removeAuthCode.mockResolvedValue(undefined);
      clientService.validateClientCredentials.mockResolvedValue(false);

      await expect(service.exchangeAuthorizationCodeForToken(tokenDto)).rejects.toThrow(
        'Invalid client credentials',
      );
    });

    it('enforces PKCE for all clients', async () => {
      const codeWithoutPKCE = { ...mockAuthCode, code_challenge: undefined };
      // biome-ignore lint/suspicious/noExplicitAny: Override to test PKCE enforcement
      store.getAuthCode.mockResolvedValue(codeWithoutPKCE as any);
      store.removeAuthCode.mockResolvedValue(undefined);
      clientService.validateClientCredentials.mockResolvedValue(true);

      await expect(service.exchangeAuthorizationCodeForToken(tokenDto)).rejects.toThrow(
        'PKCE is required for all clients',
      );
    });
  });

  describe('introspectToken', () => {
    const introspectDto = {
      token: 'test-token',
      token_type_hint: 'access_token' as const,
      client_id: 'client-123',
      client_secret: 'client-secret',
    };

    it('provides metadata for active access token', async () => {
      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.validateAccessToken.mockResolvedValue({
        userId: 'user-123',
        clientId: 'client-123',
        scope: 'read write',
        resource: 'http://api.example.com',
        userProfileId: 'profile-123',
      });

      const result = await service.introspectToken(introspectDto);

      expect(result.active).toBe(true);
      expect(result.username).toBe('user-123');
      expect(result.scope).toBe('read write');
      expect(result.token_type).toBe('Bearer');
    });

    it('denies introspection for tokens from other clients', async () => {
      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.validateAccessToken.mockResolvedValue({
        userId: 'user-123',
        clientId: 'other-client',
        scope: 'read write',
        resource: 'http://api.example.com',
        userProfileId: 'profile-123',
      });

      const result = await service.introspectToken(introspectDto);

      expect(result.active).toBe(false);
    });

    it('marks expired tokens as inactive', async () => {
      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.validateAccessToken.mockResolvedValue(null);

      const result = await service.introspectToken(introspectDto);

      expect(result.active).toBe(false);
    });
  });

  describe('revokeToken', () => {
    const revokeDto = {
      token: 'test-token',
      token_type_hint: 'access_token' as const,
      client_id: 'client-123',
      client_secret: 'client-secret',
    };

    it('revokes access tokens silently', async () => {
      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.validateAccessToken.mockResolvedValue({
        userId: 'user-123',
        clientId: 'client-123',
        scope: 'read write',
        resource: 'http://api.example.com',
        userProfileId: 'profile-123',
      });
      store.removeAccessToken.mockResolvedValue(undefined);

      await service.revokeToken(revokeDto);

      expect(store.removeAccessToken).toHaveBeenCalledWith('test-token');
    });

    it('revokes entire token family for refresh tokens', async () => {
      const refreshRevokeDto = { ...revokeDto, token_type_hint: 'refresh_token' as const };

      clientService.validateClientCredentials.mockResolvedValue(true);
      tokenService.validateRefreshToken.mockResolvedValue({
        userId: 'user-123',
        clientId: 'client-123',
        scope: 'read write',
        resource: 'http://api.example.com',
        userProfileId: 'profile-123',
        familyId: 'family-123',
        generation: 1,
        expiresAt: new Date(Date.now() + 86400000),
      });
      store.revokeTokenFamily?.mockResolvedValue(undefined);

      await service.revokeToken(refreshRevokeDto);

      expect(store.revokeTokenFamily).toHaveBeenCalledWith('family-123');
    });

    it('handles revocation attempts gracefully per RFC 7009', async () => {
      clientService.validateClientCredentials.mockResolvedValue(false);

      // Should not throw, per RFC 7009
      await expect(service.revokeToken(revokeDto)).resolves.not.toThrow();
    });
  });
});
