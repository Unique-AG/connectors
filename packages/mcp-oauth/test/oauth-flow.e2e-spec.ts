import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig, MockOAuthStore } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';

describe('OAuth Authorization Code Flow (E2E)', () => {
  let app: INestApplication;
  let oauthStore: MockOAuthStore;
  // biome-ignore lint/suspicious/noExplicitAny: Allowed for testing
  let registeredClient: any;

  beforeAll(async () => {
    const config = createMockModuleConfig();
    oauthStore = config.oauthStore as MockOAuthStore;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [
        McpOAuthModule.forRootAsync({
          useFactory: () => config,
        }),
      ],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    oauthStore.clear();

    const response = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Test MCP Client',
        redirect_uris: ['http://localhost:4000/callback'],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });

    expect(response.status).toBe(201);
    expect(response.body.client_id).toBeDefined();
    expect(response.body.client_id_issued_at).toBeDefined();
    expect(typeof response.body.client_id_issued_at).toBe('number');

    registeredClient = response.body;
  });

  describe('Complete OAuth Flow', () => {
    it('completes authorization code flow with PKCE', async () => {
      const codeVerifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
      const codeChallenge = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'; // SHA256 of verifier
      const clientState = 'client-state-123';

      // Step 1: Initiate authorization
      const authResponse = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
        response_type: 'code',
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:4000/callback',
        code_challenge: codeChallenge,
        code_challenge_method: 'S256',
        state: clientState,
        scope: 'offline_access mcp:read',
      });

      expect(authResponse.status).toBe(302);
      expect(authResponse.headers.location).toContain('state=');
      expect(authResponse.headers.location).toContain('code=mock-provider-code');

      // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
      const callbackUrl = new URL(authResponse.headers.location!);
      const providerState = callbackUrl.searchParams.get('state');
      const providerCode = callbackUrl.searchParams.get('code');

      // Step 2: Handle callback (simulating provider redirect back)
      const callbackResponse = await request(app.getHttpServer())
        .get(OAUTH_ENDPOINTS.callback)
        .query({
          state: providerState,
          code: providerCode,
        });

      expect(callbackResponse.status).toBe(302);
      expect(callbackResponse.headers.location).toContain('http://localhost:4000/callback');

      // Extract authorization code from redirect
      // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
      const clientCallbackUrl = new URL(callbackResponse.headers.location!);
      const authCode = clientCallbackUrl.searchParams.get('code');
      const returnedState = clientCallbackUrl.searchParams.get('state');

      expect(authCode).toBeDefined();
      expect(returnedState).toBe(clientState);

      // Step 3: Exchange authorization code for tokens
      const tokenResponse = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:4000/callback',
        client_id: registeredClient.client_id,
        code_verifier: codeVerifier,
      });

      expect(tokenResponse.status).toBe(200);
      expect(tokenResponse.body).toMatchObject({
        access_token: expect.any(String),
        token_type: 'Bearer',
        expires_in: 3600,
        refresh_token: expect.any(String),
        scope: 'offline_access mcp:read',
      });

      const { access_token, refresh_token } = tokenResponse.body;

      // Step 4: Introspect the access token
      const introspectResponse = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.introspect)
        .send({
          token: access_token,
          client_id: registeredClient.client_id,
          token_type_hint: 'access_token',
        });

      expect(introspectResponse.status).toBe(200);
      expect(introspectResponse.body).toMatchObject({
        active: true,
        scope: 'offline_access mcp:read',
        client_id: registeredClient.client_id,
        username: 'testuser',
      });

      // Step 5: Refresh the token
      const refreshResponse = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: refresh_token,
        client_id: registeredClient.client_id,
        scope: 'mcp:read', // Request reduced scope
      });

      expect(refreshResponse.status).toBe(200);
      expect(refreshResponse.body).toMatchObject({
        access_token: expect.any(String),
        token_type: 'Bearer',
        expires_in: 3600,
        refresh_token: expect.any(String),
        scope: 'mcp:read', // Reduced scope
      });

      const newAccessToken = refreshResponse.body.access_token;

      // Step 6: Revoke the new access token
      const revokeResponse = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.revoke).send({
        token: newAccessToken,
        client_id: registeredClient.client_id,
        token_type_hint: 'access_token',
      });

      expect(revokeResponse.status).toBe(200);

      // Step 7: Verify token is revoked
      const introspectRevokedResponse = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.introspect)
        .send({
          token: newAccessToken,
          client_id: registeredClient.client_id,
        });

      expect(introspectRevokedResponse.status).toBe(200);
      expect(introspectRevokedResponse.body).toEqual({ active: false });
    });
  });

  describe('RFC 7591 Dynamic Client Registration', () => {
    it('registers a public client without client_id in request and returns RFC 7591 compliant response', async () => {
      const response = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.register)
        .send({
          client_name: 'Dynamic Public Client',
          redirect_uris: ['http://localhost:5000/callback'],
          grant_types: ['authorization_code', 'refresh_token'],
          response_types: ['code'],
          token_endpoint_auth_method: 'none',
        });

      expect(response.status).toBe(201);
      expect(response.body).toMatchObject({
        client_id: expect.any(String),
        client_name: 'Dynamic Public Client',
        redirect_uris: ['http://localhost:5000/callback'],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
        client_id_issued_at: expect.any(Number),
      });
      expect(response.body.client_secret).toBeUndefined();
      expect(response.body.client_secret_expires_at).toBeUndefined();
    });

    it('registers a confidential client and returns client_secret with client_secret_expires_at', async () => {
      const response = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.register)
        .send({
          client_name: 'Dynamic Confidential Client',
          redirect_uris: ['http://localhost:5000/callback'],
          grant_types: ['authorization_code', 'refresh_token'],
          response_types: ['code'],
          token_endpoint_auth_method: 'client_secret_basic',
        });

      expect(response.status).toBe(201);
      expect(response.body).toMatchObject({
        client_id: expect.any(String),
        client_name: 'Dynamic Confidential Client',
        client_secret: expect.any(String),
        client_id_issued_at: expect.any(Number),
        client_secret_expires_at: 0,
        token_endpoint_auth_method: 'client_secret_basic',
      });
    });

    it('generates unique client_id for each registration', async () => {
      const response1 = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.register)
        .send({
          client_name: 'Client One',
          redirect_uris: ['http://localhost:5000/callback'],
          grant_types: ['authorization_code'],
          response_types: ['code'],
          token_endpoint_auth_method: 'none',
        });

      const response2 = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.register)
        .send({
          client_name: 'Client Two',
          redirect_uris: ['http://localhost:5001/callback'],
          grant_types: ['authorization_code'],
          response_types: ['code'],
          token_endpoint_auth_method: 'none',
        });

      expect(response1.status).toBe(201);
      expect(response2.status).toBe(201);
      expect(response1.body.client_id).not.toBe(response2.body.client_id);
    });
  });

  describe('Discovery Endpoints', () => {
    it('provides OAuth authorization server metadata', async () => {
      const response = await request(app.getHttpServer())
        .get('/.well-known/oauth-authorization-server')
        .expect(200);

      expect(response.body).toMatchObject({
        issuer: 'http://localhost:3000',
        authorization_endpoint: 'http://localhost:3000/oauth/authorize',
        token_endpoint: 'http://localhost:3000/oauth/token',
        registration_endpoint: 'http://localhost:3000/oauth/register',
        response_types_supported: ['code'],
        grant_types_supported: ['authorization_code', 'refresh_token'],
        code_challenge_methods_supported: ['plain', 'S256'],
      });
    });

    it('provides protected resource metadata', async () => {
      const response = await request(app.getHttpServer())
        .get('/.well-known/oauth-protected-resource')
        .expect(200);

      expect(response.body).toMatchObject({
        resource: 'http://localhost:3000/mcp',
        authorization_servers: ['http://localhost:3000'],
        scopes_supported: ['offline_access', 'mcp:read', 'mcp:write'],
        bearer_methods_supported: ['header'],
        mcp_versions_supported: ['2025-06-18'],
      });
    });
  });
});
