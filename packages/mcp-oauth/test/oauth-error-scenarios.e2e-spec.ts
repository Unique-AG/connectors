/** biome-ignore-all lint/suspicious/noExplicitAny: Allowed for testing */
import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig, MockOAuthStore } from '../src/__mocks__';
import { McpOAuthThrottlerGuard } from '../src/guards/mcp-oauth-throttler.guard';
import { McpOAuthModule } from '../src/mcp-oauth.module';

describe('OAuth Error Scenarios (E2E)', () => {
  let app: INestApplication;
  let oauthStore: MockOAuthStore;
  let registeredClient: any;
  let confidentialClient: any;
  let pkceTestClient: any;

  beforeAll(async () => {
    const config = createMockModuleConfig();
    oauthStore = config.oauthStore as MockOAuthStore;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [
        McpOAuthModule.forRootAsync({
          useFactory: () => config,
        }),
      ],
    })
      .overrideGuard(McpOAuthThrottlerGuard)
      .useValue({ canActivate: () => true })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    // Register clients once for the entire test suite
    const publicResponse = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Test Public Client',
        redirect_uris: ['http://localhost:4000/callback'],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    registeredClient = publicResponse.body;

    const confidentialResponse = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Test Confidential Client',
        redirect_uris: ['http://localhost:5000/callback'],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'client_secret_basic',
      });
    confidentialClient = confidentialResponse.body;

    // Register client for PKCE tests (used by multiple tests)
    const pkceResponse = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'PKCE Test Client',
        redirect_uris: ['http://localhost:5000/callback'],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    pkceTestClient = pkceResponse.body;
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    // Clear only dynamic data (tokens, sessions, auth codes), preserve registered clients
    oauthStore.clearDynamicData();
  });

  describe('Authorization Errors', () => {
    it('rejects invalid response_type', async () => {
      const response = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'token', // Invalid for OAuth 2.1
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        state: 'test-state',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid response type',
        error: 'Bad Request',
      });
    });

    it('rejects missing client_id', async () => {
      const response = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        redirect_uri: 'http://localhost:4000/callback',
        state: 'test-state',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Missing client_id parameter',
        error: 'Bad Request',
      });
    });

    it('rejects non-existent client', async () => {
      const response = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: 'non-existent-client',
        redirect_uri: 'http://localhost:4000/callback',
        state: 'test-state',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid client_id parameter',
        error: 'Bad Request',
      });
    });

    it('rejects unregistered redirect_uri', async () => {
      const response = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: registeredClient.client_id,
        redirect_uri: 'http://evil.com/callback',
        state: 'test-state',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid redirect_uri parameter',
        error: 'Bad Request',
      });
    });

    it('rejects invalid resource parameter', async () => {
      const response = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        resource: 'http://wrong-resource.com',
        state: 'test-state',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid resource parameter',
        error: 'Bad Request',
      });
    });

    it('rejects authorization requests without PKCE (OAuth 2.1 compliance)', async () => {
      // Attempt authorization without PKCE (should fail for OAuth 2.1 compliance)
      const authResponse = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: pkceTestClient.client_id,
        redirect_uri: 'http://localhost:5000/callback',
        state: 'state-456',
      });

      expect(authResponse.status).toBe(400);
      expect(authResponse.body.message).toBe('code_challenge parameter is required');
    });

    it('rejects authorization requests without code_challenge_method (OAuth 2.1 compliance)', async () => {
      // Attempt authorization with code_challenge but without code_challenge_method
      const authResponse = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: pkceTestClient.client_id,
        redirect_uri: 'http://localhost:5000/callback',
        state: 'state-456',
        code_challenge: 'challenge-123',
      });

      expect(authResponse.status).toBe(400);
      expect(authResponse.body.message).toBe('code_challenge_method parameter is required');
    });

    it('rejects authorization requests with invalid code_challenge_method (OAuth 2.1 compliance)', async () => {
      // Attempt authorization with plain code_challenge_method (not allowed in OAuth 2.1)
      const authResponse = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: pkceTestClient.client_id,
        redirect_uri: 'http://localhost:5000/callback',
        state: 'state-456',
        code_challenge: 'challenge-123',
        code_challenge_method: 'plain',
      });

      expect(authResponse.status).toBe(400);
      expect(authResponse.body.message).toBe('code_challenge_method must be S256');
    });
  });

  describe('Token Exchange Errors', () => {
    it('rejects invalid authorization code', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: 'invalid-code-123',
        redirect_uri: 'http://localhost:4000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'a-44-character-long-code-verifier-to-statisfy-zod',
      });

      expect(response.status).toBe(400);

      expect(response.body).toMatchObject({
        message: 'Invalid or expired authorization code',
      });
    });

    it('rejects expired authorization code', async () => {
      // Create an expired auth code directly in store
      const expiredCode = 'expired-code-123';
      await oauthStore.storeAuthCode({
        code: expiredCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        user_id: 'user-123',
        user_profile_id: 'profile-123',
        scope: 'offline_access',
        code_challenge: '',
        code_challenge_method: 'plain',
        expires_at: Date.now() - 1000, // Expired
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: expiredCode,
        redirect_uri: 'http://localhost:4000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'a-44-character-long-code-verifier-to-statisfy-zod',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid or expired authorization code',
      });
    });

    it('rejects invalid PKCE verifier', async () => {
      // Create auth code with PKCE challenge
      const validCode = 'pkce-code-123';
      await oauthStore.storeAuthCode({
        code: validCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        user_id: 'user-123',
        user_profile_id: 'profile-123',
        scope: 'offline_access',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
        resource: 'http://localhost:3000/mcp',
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: validCode,
        redirect_uri: 'http://localhost:4000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'wrong-verifier-that-is-44-characters-long-to-statisfy-zod',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: 'Invalid request',
      });
    });

    it('rejects invalid refresh token', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'invalid-refresh-token',
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        error: 'invalid_grant',
      });
    });

    it('rejects unsupported grant type', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'password',
        username: 'user',
        password: 'pass',
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        message: expect.stringContaining('Validation failed'),
      });
    });
  });

  describe('Client Authentication Errors', () => {
    const validCode = 'pkce-code-123';
    beforeEach(async () => {
      await oauthStore.storeAuthCode({
        code: validCode,
        client_id: confidentialClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        user_id: 'user-123',
        user_profile_id: 'profile-123',
        scope: 'offline_access',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
        resource: 'http://localhost:3000/mcp',
      });
    });

    it('rejects confidential client without credentials', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: validCode,
        redirect_uri: 'http://localhost:5000/callback',
        client_id: confidentialClient.client_id,
        // Missing client_secret
        code_verifier: 'a-44-character-long-code-verifier-to-statisfy-zod',
      });

      expect(response.status).toBe(401);
      expect(response.body).toMatchObject({
        message: 'Invalid client credentials',
      });
    });

    it('rejects confidential client with wrong secret', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: validCode,
        redirect_uri: 'http://localhost:5000/callback',
        client_id: confidentialClient.client_id,
        client_secret: 'wrong-secret',
        code_verifier: 'a-44-character-long-code-verifier-to-statisfy-zod',
      });

      expect(response.status).toBe(401);
      expect(response.body).toMatchObject({
        message: 'Invalid client credentials',
      });
    });

    it('rejects public client with unexpected secret', async () => {
      await oauthStore.storeAuthCode({
        code: validCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        user_id: 'user-123',
        user_profile_id: 'profile-123',
        scope: 'offline_access',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
        resource: 'http://localhost:3000/mcp',
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: validCode,
        redirect_uri: 'http://localhost:4000/callback',
        client_id: registeredClient.client_id,
        client_secret: 'unexpected-secret', // Public client shouldn't have secret
        code_verifier: 'a-44-character-long-code-verifier-to-statisfy-zod',
      });

      expect(response.status).toBe(401);
      expect(response.body).toMatchObject({
        message: 'Invalid client credentials',
      });
    });
  });

  describe('Token Introspection Errors', () => {
    it('returns inactive for invalid token', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.introspect).send({
        token: 'invalid-token',
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({ active: false });
    });

    it('returns inactive for wrong client credentials', async () => {
      // Store a valid token
      await oauthStore.storeAccessToken('valid-token', {
        clientId: 'different-client',
        userId: 'user-123',
        userProfileId: 'profile-123',
        scope: 'offline_access',
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 3600000),
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.introspect).send({
        token: 'valid-token',
        client_id: registeredClient.client_id, // Wrong client
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({ active: false });
    });

    it('does not leak error details on introspection failure', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.introspect).send({
        token: 'some-token',
        client_id: 'non-existent-client',
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({ active: false });
      expect(response.body).not.toHaveProperty('error');
      expect(response.body).not.toHaveProperty('error_description');
    });
  });

  describe('Token Revocation Errors', () => {
    it('returns success even for invalid token', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.revoke).send({
        token: 'invalid-token',
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({});
    });

    it('returns success for wrong client', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.revoke).send({
        token: 'some-token',
        client_id: 'wrong-client',
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({});
    });

    it('does not leak error details on revocation failure', async () => {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.revoke).send({
        token: 'some-token',
        client_id: 'non-existent-client',
      });

      expect(response.status).toBe(200);
      expect(response.body).toEqual({});
      expect(response.body).not.toHaveProperty('error');
      expect(response.body).not.toHaveProperty('error_description');
    });
  });

  describe('Scope Validation During Token Refresh', () => {
    it('rejects refresh token request with scope not originally granted', async () => {
      // Create a valid refresh token with limited scope
      const originalScope = 'mcp:read';
      const unauthorizedScope = 'mcp:write';

      await oauthStore.storeRefreshToken('valid-refresh-token', {
        userId: 'user-123',
        clientId: registeredClient.client_id,
        scope: originalScope,
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000), // 24 hours
        userProfileId: 'profile-123',
        familyId: 'family-123',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'valid-refresh-token',
        client_id: registeredClient.client_id,
        scope: unauthorizedScope, // Requesting scope not originally granted
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        error: 'invalid_scope',
      });
    });

    it('rejects refresh token request with multiple scopes where some were not originally granted', async () => {
      // Create a valid refresh token with limited scope
      const originalScope = 'mcp:read offline_access';
      const requestedScope = 'mcp:read mcp:write offline_access'; // includes unauthorized mcp:write

      await oauthStore.storeRefreshToken('valid-refresh-token-2', {
        userId: 'user-123',
        clientId: registeredClient.client_id,
        scope: originalScope,
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000), // 24 hours
        userProfileId: 'profile-123',
        familyId: 'family-124',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'valid-refresh-token-2',
        client_id: registeredClient.client_id,
        scope: requestedScope,
      });

      expect(response.status).toBe(400);
      expect(response.body).toMatchObject({
        error: 'invalid_scope',
      });
    });

    it('allows refresh token request with subset of originally granted scopes', async () => {
      // Create a valid refresh token with multiple scopes
      const originalScope = 'mcp:read mcp:write offline_access';
      const requestedScope = 'mcp:read'; // subset of original

      await oauthStore.storeRefreshToken('valid-refresh-token-3', {
        userId: 'user-123',
        clientId: registeredClient.client_id,
        scope: originalScope,
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000), // 24 hours
        userProfileId: 'profile-123',
        familyId: 'family-125',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'valid-refresh-token-3',
        client_id: registeredClient.client_id,
        scope: requestedScope,
      });

      expect(response.status).toBe(200);
      expect(response.body).toMatchObject({
        access_token: expect.any(String),
        token_type: 'Bearer',
        expires_in: 3600,
        refresh_token: expect.any(String),
        scope: requestedScope, // Should match requested subset
      });
    });

    it('uses original scope when no scope parameter provided in refresh request', async () => {
      // Create a valid refresh token
      const originalScope = 'mcp:read mcp:write offline_access';

      await oauthStore.storeRefreshToken('valid-refresh-token-4', {
        userId: 'user-123',
        clientId: registeredClient.client_id,
        scope: originalScope,
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000), // 24 hours
        userProfileId: 'profile-123',
        familyId: 'family-126',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'valid-refresh-token-4',
        client_id: registeredClient.client_id,
        // No scope parameter - should use original scope
      });

      expect(response.status).toBe(200);
      expect(response.body).toMatchObject({
        access_token: expect.any(String),
        token_type: 'Bearer',
        expires_in: 3600,
        refresh_token: expect.any(String),
        scope: originalScope, // Should match original scope
      });
    });
  });
});
