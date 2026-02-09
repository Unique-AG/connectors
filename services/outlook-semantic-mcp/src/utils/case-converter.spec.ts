/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { describe, expect, it } from 'vitest';
import {
  fromDrizzleAuthCodeRow,
  fromDrizzleOAuthClientRow,
  fromDrizzleSessionRow,
  toDrizzleAuthCodeInsert,
  toDrizzleOAuthClientInsert,
  toDrizzleSessionInsert,
} from './case-converter';

describe('case-converter', () => {
  describe('OAuth Client conversion', () => {
    const mockOAuthClient = {
      client_id: 'test-client-id',
      client_secret: 'test-secret',
      client_name: 'Test Client',
      client_description: 'Test Description',
      logo_uri: 'https://example.com/logo.png',
      client_uri: 'https://example.com',
      developer_name: 'Test Developer',
      developer_email: 'test@example.com',
      redirect_uris: ['https://example.com/callback'],
      grant_types: ['authorization_code'],
      response_types: ['code'],
      token_endpoint_auth_method: 'client_secret_post',
      created_at: new Date('2023-01-01'),
      updated_at: new Date('2023-01-02'),
    };

    const mockDrizzleClient = {
      clientId: 'test-client-id',
      clientSecret: 'test-secret',
      clientName: 'Test Client',
      clientDescription: 'Test Description',
      logoUri: 'https://example.com/logo.png',
      clientUri: 'https://example.com',
      developerName: 'Test Developer',
      developerEmail: 'test@example.com',
      redirectUris: ['https://example.com/callback'],
      grantTypes: ['authorization_code'],
      responseTypes: ['code'],
      tokenEndpointAuthMethod: 'client_secret_post',
      createdAt: new Date('2023-01-01'),
      updatedAt: new Date('2023-01-02'),
    };

    it('converts OAuthClient to Drizzle format', () => {
      const result = toDrizzleOAuthClientInsert(mockOAuthClient);

      expect(result).toEqual(mockDrizzleClient);
    });

    it('converts Drizzle client to OAuthClient format', () => {
      const result = fromDrizzleOAuthClientRow(mockDrizzleClient as any);

      expect(result).toEqual(mockOAuthClient);
    });

    it('handles null values in Drizzle to OAuth conversion', () => {
      const drizzleClientWithNulls = {
        ...mockDrizzleClient,
        clientSecret: null,
        clientDescription: null,
        logoUri: null,
        clientUri: null,
        developerName: null,
        developerEmail: null,
      };

      const result = fromDrizzleOAuthClientRow(drizzleClientWithNulls as any);

      expect(result).toEqual({
        ...mockOAuthClient,
        client_secret: undefined,
        client_description: undefined,
        logo_uri: undefined,
        client_uri: undefined,
        developer_name: undefined,
        developer_email: undefined,
      });
    });
  });

  describe('Authorization Code conversion', () => {
    const mockAuthCode = {
      code: 'test-auth-code',
      user_id: 'user-123',
      client_id: 'client-123',
      redirect_uri: 'https://example.com/callback',
      code_challenge: 'challenge',
      code_challenge_method: 'S256',
      resource: 'https://example.com/resource',
      scope: 'read write',
      expires_at: 1672531200000, // 2023-01-01 00:00:00 UTC
      user_profile_id: 'profile-123',
    };

    const mockDrizzleAuthCode = {
      code: 'test-auth-code',
      userId: 'user-123',
      clientId: 'client-123',
      redirectUri: 'https://example.com/callback',
      codeChallenge: 'challenge',
      codeChallengeMethod: 'S256',
      resource: 'https://example.com/resource',
      scope: 'read write',
      expiresAt: new Date(1672531200000),
      userProfileId: 'profile-123',
    };

    it('converts AuthorizationCode to Drizzle format', () => {
      const result = toDrizzleAuthCodeInsert(mockAuthCode);

      expect(result).toEqual(mockDrizzleAuthCode);
    });

    it('converts Drizzle auth code to AuthorizationCode format', () => {
      const result = fromDrizzleAuthCodeRow(mockDrizzleAuthCode as any);

      expect(result).toEqual(mockAuthCode);
    });

    it('handles null resource and scope in Drizzle to AuthCode conversion', () => {
      const drizzleAuthCodeWithNulls = {
        ...mockDrizzleAuthCode,
        resource: null,
        scope: null,
      };

      const result = fromDrizzleAuthCodeRow(drizzleAuthCodeWithNulls as any);

      expect(result).toEqual({
        ...mockAuthCode,
        resource: undefined,
        scope: undefined,
      });
    });
  });

  describe('OAuth Session conversion', () => {
    const mockOAuthSession = {
      sessionId: 'session-123',
      state: 'state-value',
      clientId: 'client-123',
      redirectUri: 'https://example.com/callback',
      codeChallenge: 'challenge',
      codeChallengeMethod: 'S256',
      oauthState: 'oauth-state',
      scope: 'read write',
      resource: 'https://example.com/resource',
      expiresAt: 1672531200000,
    };

    const mockDrizzleSession = {
      sessionId: 'session-123',
      state: 'state-value',
      clientId: 'client-123',
      redirectUri: 'https://example.com/callback',
      codeChallenge: 'challenge',
      codeChallengeMethod: 'S256',
      oauthState: 'oauth-state',
      scope: 'read write',
      resource: 'https://example.com/resource',
      expiresAt: new Date(1672531200000),
    };

    it('converts OAuthSession to Drizzle format', () => {
      const result = toDrizzleSessionInsert(mockOAuthSession);

      expect(result).toEqual(mockDrizzleSession);
    });

    it('converts Drizzle session to OAuthSession format', () => {
      const result = fromDrizzleSessionRow(mockDrizzleSession as any);

      expect(result).toEqual(mockOAuthSession);
    });

    it('handles null values in Drizzle to Session conversion', () => {
      const drizzleSessionWithNulls = {
        ...mockDrizzleSession,
        clientId: null,
        redirectUri: null,
        codeChallenge: null,
        codeChallengeMethod: null,
        oauthState: null,
        scope: null,
        resource: null,
      };

      const result = fromDrizzleSessionRow(drizzleSessionWithNulls as any);

      expect(result).toEqual({
        ...mockOAuthSession,
        clientId: undefined,
        redirectUri: undefined,
        codeChallenge: undefined,
        codeChallengeMethod: undefined,
        oauthState: undefined,
        scope: undefined,
        resource: undefined,
      });
    });
  });
});
