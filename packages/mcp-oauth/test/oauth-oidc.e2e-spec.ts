/** biome-ignore-all lint/suspicious/noExplicitAny: need to use any to access private properties */
import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import { ThrottlerGuard } from '@nestjs/throttler';
import * as jwt from 'jsonwebtoken';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig, MockOAuthStore } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';

describe('OAuth OIDC Flow (E2E)', () => {
  let app: INestApplication;
  let oauthStore: MockOAuthStore;
  let registeredClient: any;
  let mockConfig: any;

  beforeAll(async () => {
    mockConfig = createMockModuleConfig();
    // Add OIDC configuration
    mockConfig.jwtSigningKey = 'test-jwt-signing-key';
    mockConfig.jwtSigningAlgorithm = 'HS256';
    mockConfig.idTokenExpiresIn = 3600;
    mockConfig.authorizationServerMetadata.scopesSupported = [
      'openid',
      'offline_access',
      'profile',
      'email',
    ];
    mockConfig.protectedResourceMetadata.scopesSupported = [
      'openid',
      'offline_access',
      'profile',
      'email',
    ];

    oauthStore = mockConfig.oauthStore as MockOAuthStore;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [
        McpOAuthModule.forRootAsync({
          useFactory: () => mockConfig,
        }),
      ],
    })
      .overrideGuard(ThrottlerGuard)
      .useValue({ canActivate: () => true })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    // Register a test client
    const response = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'OIDC Test Client',
        redirect_uris: ['http://localhost:3000/callback'],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    registeredClient = response.body;
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    oauthStore.clearDynamicData();
  });

  describe('OIDC Discovery', () => {
    it('provides OpenID Connect discovery endpoint', async () => {
      const response = await request(app.getHttpServer()).get('/.well-known/openid-configuration');

      expect(response.status).toBe(200);
      expect(response.body).toMatchObject({
        issuer: 'http://localhost:3000',
        authorization_endpoint: 'http://localhost:3000/oauth/authorize',
        token_endpoint: 'http://localhost:3000/oauth/token',
        jwks_uri: 'http://localhost:3000/.well-known/jwks.json',
        registration_endpoint: 'http://localhost:3000/oauth/register',
        revocation_endpoint: 'http://localhost:3000/oauth/revoke',
        introspection_endpoint: 'http://localhost:3000/oauth/introspect',
        response_types_supported: ['code'],
        response_modes_supported: ['query'],
        grant_types_supported: ['authorization_code', 'refresh_token'],
        subject_types_supported: ['public'],
        id_token_signing_alg_values_supported: ['HS256', 'RS256'],
        scopes_supported: ['openid', 'offline_access', 'profile', 'email'],
        token_endpoint_auth_methods_supported: [
          'client_secret_basic',
          'client_secret_post',
          'none',
        ],
        code_challenge_methods_supported: ['plain', 'S256'],
      });
    });

    it('includes claims_supported in discovery metadata', async () => {
      const response = await request(app.getHttpServer()).get('/.well-known/openid-configuration');

      expect(response.status).toBe(200);
      expect(response.body.claims_supported).toContain('sub');
      expect(response.body.claims_supported).toContain('iss');
      expect(response.body.claims_supported).toContain('aud');
      expect(response.body.claims_supported).toContain('exp');
      expect(response.body.claims_supported).toContain('iat');
      expect(response.body.claims_supported).toContain('name');
      expect(response.body.claims_supported).toContain('email');
      expect(response.body.claims_supported).toContain('email_verified');
    });
  });

  describe('Authorization Code Exchange with openid scope', () => {
    it('returns ID token when openid scope is requested', async () => {
      // Create an authorization code with openid scope
      const authCode = 'oidc-auth-code-123';
      const userProfileId = 'profile-123';

      // Store user profile
      await oauthStore.upsertUserProfile({
        profile: {
          id: 'user-123',
          username: 'testuser',
          displayName: 'Test User',
          email: 'test@example.com',
        },
        accessToken: 'provider-token',
        refreshToken: 'provider-refresh',
        provider: 'test',
      });

      // Store authorization code with openid scope
      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'testuser',
        user_profile_id: userProfileId,
        scope: 'openid offline_access',
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('access_token');
      expect(response.body).toHaveProperty('refresh_token');
      expect(response.body).toHaveProperty('id_token');
      expect(response.body.token_type).toBe('Bearer');
      expect(response.body.expires_in).toBe(3600);
      expect(response.body.scope).toBe('openid offline_access');

      // Verify ID token structure and claims
      const idToken = response.body.id_token;
      const decoded = jwt.decode(idToken) as jwt.JwtPayload;

      expect(decoded).toBeDefined();
      expect(decoded.iss).toBe('http://localhost:3000');
      expect(decoded.sub).toBe('testuser');
      expect(decoded.aud).toBe(registeredClient.client_id);
      expect(decoded.azp).toBe(registeredClient.client_id);
      expect(decoded.exp).toBeGreaterThan(Math.floor(Date.now() / 1000));
      expect(decoded.iat).toBeLessThanOrEqual(Math.floor(Date.now() / 1000));
    });

    it('includes profile claims in ID token when profile scope is requested', async () => {
      const authCode = 'profile-auth-code-123';
      const userProfileId = 'profile-456';

      // Store user profile with detailed information
      await (oauthStore as any).userProfiles.set(userProfileId, {
        profile_id: userProfileId,
        provider: 'test',
        id: 'user-456',
        username: 'johndoe',
        displayName: 'John Doe',
        email: 'john@example.com',
        avatarUrl: 'https://example.com/avatar.jpg',
        raw: {},
      });

      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'johndoe',
        user_profile_id: userProfileId,
        scope: 'openid profile',
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('id_token');

      const decoded = jwt.decode(response.body.id_token) as jwt.JwtPayload;
      expect(decoded.name).toBe('John Doe');
      expect(decoded.preferred_username).toBe('johndoe');
      expect(decoded.picture).toBe('https://example.com/avatar.jpg');
    });

    it('includes email claims in ID token when email scope is requested', async () => {
      const authCode = 'email-auth-code-123';
      const userProfileId = 'profile-789';

      await (oauthStore as any).userProfiles.set(userProfileId, {
        profile_id: userProfileId,
        provider: 'test',
        id: 'user-789',
        username: 'janedoe',
        email: 'jane@example.com',
        displayName: 'Jane Doe',
        raw: {},
      });

      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'janedoe',
        user_profile_id: userProfileId,
        scope: 'openid email',
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('id_token');

      const decoded = jwt.decode(response.body.id_token) as jwt.JwtPayload;
      expect(decoded.email).toBe('jane@example.com');
      expect(decoded.email_verified).toBe(false);
    });

    it('does not return ID token when openid scope is not requested', async () => {
      const authCode = 'no-openid-code-123';

      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'testuser',
        user_profile_id: 'profile-123',
        scope: 'offline_access', // No openid scope
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('access_token');
      expect(response.body).toHaveProperty('refresh_token');
      expect(response.body).not.toHaveProperty('id_token');
      expect(response.body.scope).toBe('offline_access');
    });
  });

  describe('Token Refresh with openid scope', () => {
    it('returns new ID token when refreshing with openid scope', async () => {
      // Store a refresh token with openid scope
      const refreshToken = 'oidc-refresh-token-123';
      const userProfileId = 'profile-refresh-123';

      await (oauthStore as any).userProfiles.set(userProfileId, {
        profile_id: userProfileId,
        provider: 'test',
        id: 'user-refresh',
        username: 'refreshuser',
        displayName: 'Refresh User',
        email: 'refresh@example.com',
        raw: {},
      });

      await oauthStore.storeRefreshToken(refreshToken, {
        userId: 'refreshuser',
        clientId: registeredClient.client_id,
        scope: 'openid offline_access profile',
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000),
        userProfileId,
        familyId: 'family-123',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('access_token');
      expect(response.body).toHaveProperty('refresh_token');
      expect(response.body).toHaveProperty('id_token');

      // Verify new ID token
      const decoded = jwt.decode(response.body.id_token) as jwt.JwtPayload;
      expect(decoded.sub).toBe('refreshuser');
      expect(decoded.name).toBe('Refresh User');
      expect(decoded.preferred_username).toBe('refreshuser');
    });

    it('maintains ID token when refreshing with reduced scope that still includes openid', async () => {
      const refreshToken = 'reduced-scope-refresh-123';
      const userProfileId = 'profile-reduced-123';

      await (oauthStore as any).userProfiles.set(userProfileId, {
        profile_id: userProfileId,
        provider: 'test',
        id: 'user-reduced',
        username: 'reduceduser',
        displayName: 'Reduced User',
        email: 'reduced@example.com',
        raw: {},
      });

      await oauthStore.storeRefreshToken(refreshToken, {
        userId: 'reduceduser',
        clientId: registeredClient.client_id,
        scope: 'openid offline_access profile email',
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000),
        userProfileId,
        familyId: 'family-456',
        generation: 0,
      });

      // Request only openid scope (reduced from original)
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: registeredClient.client_id,
        scope: 'openid offline_access', // Reduced scope
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('id_token');

      // ID token should not have profile claims since profile scope was not requested
      const decoded = jwt.decode(response.body.id_token) as jwt.JwtPayload;
      expect(decoded.sub).toBe('reduceduser');
      expect(decoded.name).toBeUndefined(); // No profile scope
      expect(decoded.email).toBeUndefined(); // No email scope
    });

    it('does not return ID token when refreshing without openid scope', async () => {
      const refreshToken = 'no-openid-refresh-123';

      await oauthStore.storeRefreshToken(refreshToken, {
        userId: 'nooidcuser',
        clientId: registeredClient.client_id,
        scope: 'offline_access', // No openid
        resource: 'http://localhost:3000/mcp',
        expiresAt: new Date(Date.now() + 86400000),
        userProfileId: 'profile-no-oidc',
        familyId: 'family-789',
        generation: 0,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: registeredClient.client_id,
      });

      expect(response.status).toBe(200);
      expect(response.body).toHaveProperty('access_token');
      expect(response.body).toHaveProperty('refresh_token');
      expect(response.body).not.toHaveProperty('id_token');
    });
  });

  describe('ID Token Security', () => {
    it('signs ID token with configured algorithm', async () => {
      const authCode = 'security-auth-code-123';

      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'secureuser',
        user_profile_id: 'profile-secure',
        scope: 'openid',
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      expect(response.status).toBe(200);

      // Verify token signature
      const idToken = response.body.id_token;
      const decoded = jwt.decode(idToken, { complete: true }) as jwt.Jwt;

      expect(decoded.header.alg).toBe('HS256');
      expect(decoded.header.typ).toBe('JWT');
      expect(decoded.header.kid).toBe('default');

      // Verify token can be validated with the signing key
      const verified = jwt.verify(idToken, mockConfig.jwtSigningKey || mockConfig.hmacSecret, {
        algorithms: ['HS256'],
        issuer: 'http://localhost:3000',
      });

      expect(verified).toBeDefined();
    });

    it('includes correct expiration time in ID token', async () => {
      const authCode = 'exp-auth-code-123';

      await oauthStore.storeAuthCode({
        code: authCode,
        client_id: registeredClient.client_id,
        redirect_uri: 'http://localhost:3000/callback',
        user_id: 'expuser',
        user_profile_id: 'profile-exp',
        scope: 'openid',
        resource: 'http://localhost:3000/mcp',
        code_challenge: 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM',
        code_challenge_method: 'S256',
        expires_at: Date.now() + 60000,
      });

      const beforeRequest = Math.floor(Date.now() / 1000);

      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'authorization_code',
        code: authCode,
        redirect_uri: 'http://localhost:3000/callback',
        client_id: registeredClient.client_id,
        code_verifier: 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk',
        resource: 'http://localhost:3000/mcp',
      });

      const afterRequest = Math.floor(Date.now() / 1000);

      const decoded = jwt.decode(response.body.id_token) as jwt.JwtPayload;

      // Check that exp is approximately 1 hour from now
      expect(decoded.exp).toBeGreaterThanOrEqual(beforeRequest + 3600);
      expect(decoded.exp).toBeLessThanOrEqual(afterRequest + 3600);

      // Check that iat is approximately now
      expect(decoded.iat).toBeGreaterThanOrEqual(beforeRequest);
      expect(decoded.iat).toBeLessThanOrEqual(afterRequest);
    });
  });
});
