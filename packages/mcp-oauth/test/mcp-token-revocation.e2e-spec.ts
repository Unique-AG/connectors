import { Controller, HttpCode, HttpStatus, type INestApplication, Post } from '@nestjs/common';
import { APP_GUARD } from '@nestjs/core';
import { Test, type TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { McpAuthJwtGuard, OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig, MockOAuthStore } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';
import { OpaqueTokenService } from '../src/services/opaque-token.service';

const CODE_VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
const CODE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
const REDIRECT_URI = 'http://localhost:4000/callback';

/**
 * Stands in for the MCP transport controller the real services mount, so the global
 * `McpAuthJwtGuard` has a `/mcp` route to protect.
 */
@Controller('mcp')
class TestMcpController {
  @Post()
  @HttpCode(HttpStatus.OK)
  public handle(): { ok: true } {
    return { ok: true };
  }
}

describe('MCP token revocation (E2E)', () => {
  let app: INestApplication;
  let oauthStore: MockOAuthStore;
  let tokenService: OpaqueTokenService;
  let accessToken: string;
  let refreshToken: string;
  let userProfileId: string;
  let clientId: string;

  beforeAll(async () => {
    const config = createMockModuleConfig();
    oauthStore = config.oauthStore as MockOAuthStore;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [
        McpOAuthModule.forRootAsync({
          useFactory: () => config,
        }),
      ],
      controllers: [TestMcpController],
      // The module ships the guard but leaves registration to the consuming service,
      // so the e2e has to wire it the same way the services do.
      providers: [{ provide: APP_GUARD, useClass: McpAuthJwtGuard }],
    }).compile();

    tokenService = moduleFixture.get(OpaqueTokenService);
    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(async () => {
    oauthStore.clear();

    const registerResponse = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Test MCP Client',
        redirect_uris: [REDIRECT_URI],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    expect(registerResponse.status).toBe(201);
    clientId = registerResponse.body.client_id;

    const authResponse = await request(app.getHttpServer()).get(OAUTH_ENDPOINTS.authorize).query({
      response_type: 'code',
      client_id: clientId,
      redirect_uri: REDIRECT_URI,
      code_challenge: CODE_CHALLENGE,
      code_challenge_method: 'S256',
      state: 'client-state-123',
      scope: 'offline_access mcp:read',
    });
    expect(authResponse.status).toBe(302);

    // biome-ignore lint/style/noNonNullAssertion: asserted above via the 302
    const providerRedirect = new URL(authResponse.headers.location!);
    const callbackResponse = await request(app.getHttpServer())
      .get(OAUTH_ENDPOINTS.callback)
      .query({
        state: providerRedirect.searchParams.get('state'),
        code: providerRedirect.searchParams.get('code'),
      });
    expect(callbackResponse.status).toBe(302);

    // biome-ignore lint/style/noNonNullAssertion: asserted above via the 302
    const clientRedirect = new URL(callbackResponse.headers.location!);
    const tokenResponse = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.token)
      .send({
        grant_type: 'authorization_code',
        code: clientRedirect.searchParams.get('code'),
        redirect_uri: REDIRECT_URI,
        client_id: clientId,
        code_verifier: CODE_VERIFIER,
      });
    expect(tokenResponse.status).toBe(200);

    accessToken = tokenResponse.body.access_token;
    refreshToken = tokenResponse.body.refresh_token;

    const validation = await tokenService.validateAccessToken(accessToken);
    expect(validation?.userProfileId).toBeDefined();
    // biome-ignore lint/style/noNonNullAssertion: asserted above
    userProfileId = validation!.userProfileId!;
  });

  it('accepts the access token on /mcp before the upstream credential dies', async () => {
    const response = await request(app.getHttpServer())
      .post('/mcp')
      .set('Authorization', `Bearer ${accessToken}`)
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' });

    expect(response.status).toBe(HttpStatus.OK);
  });

  it('answers /mcp with 401 and a resource_metadata challenge once the tokens are revoked', async () => {
    await tokenService.revokeAllTokensForUserProfile(userProfileId);

    const response = await request(app.getHttpServer())
      .post('/mcp')
      .set('Authorization', `Bearer ${accessToken}`)
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' });

    expect(response.status).toBe(HttpStatus.UNAUTHORIZED);
    expect(response.headers['www-authenticate']).toContain(
      'resource_metadata="http://localhost:3000/.well-known/oauth-protected-resource/mcp"',
    );
    expect(response.headers['www-authenticate']).toContain('error="invalid_token"');
    expect(response.body.error).toBe('invalid_token');
  });

  it('rejects the refresh token too, so a client cannot refresh its way back in', async () => {
    await tokenService.revokeAllTokensForUserProfile(userProfileId);

    const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
      grant_type: 'refresh_token',
      refresh_token: refreshToken,
      client_id: clientId,
    });

    expect(response.status).toBe(400);
    expect(response.body.error).toBe('invalid_grant');
  });
});
