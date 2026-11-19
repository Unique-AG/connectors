import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { OAUTH_FALLBACK_ENDPOINTS } from '../src';
import { createMockModuleConfig } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';
import { followProviderRedirect, openConsentPage, submitConsent } from './consent.helpers';

const CODE_VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
const CODE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
const REDIRECT_URI = 'http://localhost:4000/callback';

/**
 * A client that could not read the authorization server metadata uses /register, /authorize
 * and /token on the server origin and sends no `resource`. The flow has to work end to end.
 */
describe('OAuth default endpoint paths (E2E)', () => {
  let app: INestApplication;

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [McpOAuthModule.forRootAsync({ useFactory: () => createMockModuleConfig() })],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  it('completes registration, authorization, exchange and refresh on the default paths', async () => {
    const registration = await request(app.getHttpServer())
      .post(OAUTH_FALLBACK_ENDPOINTS.register)
      .send({
        client_name: 'Client without discovery',
        redirect_uris: [REDIRECT_URI],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    expect(registration.status).toBe(201);
    const clientId: string = registration.body.client_id;

    const consentPage = await openConsentPage(
      app,
      {
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        code_challenge: CODE_CHALLENGE,
        state: 'client-state',
        scope: 'offline_access',
      },
      OAUTH_FALLBACK_ENDPOINTS.authorize,
    );
    const providerRedirect = await submitConsent(app, consentPage, 'approve');
    expect(providerRedirect.status).toBe(302);

    const callback = await followProviderRedirect(
      app,
      // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
      providerRedirect.headers.location!,
      consentPage.cookie,
    );
    expect(callback.status).toBe(302);
    // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
    const code = new URL(callback.headers.location!).searchParams.get('code');
    expect(code).toBeTruthy();

    const exchange = await request(app.getHttpServer()).post(OAUTH_FALLBACK_ENDPOINTS.token).send({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: clientId,
      code_verifier: CODE_VERIFIER,
    });
    expect(exchange.status).toBe(200);
    expect(exchange.body).toMatchObject({
      access_token: expect.any(String),
      refresh_token: expect.any(String),
      token_type: 'Bearer',
    });

    const refresh = await request(app.getHttpServer()).post(OAUTH_FALLBACK_ENDPOINTS.token).send({
      grant_type: 'refresh_token',
      refresh_token: exchange.body.refresh_token,
      client_id: clientId,
    });
    expect(refresh.status).toBe(200);
    expect(refresh.body.access_token).toEqual(expect.any(String));
    expect(refresh.body.access_token).not.toBe(exchange.body.access_token);
  });

  it('issues the token for the server resource when the client sends none', async () => {
    const registration = await request(app.getHttpServer())
      .post(OAUTH_FALLBACK_ENDPOINTS.register)
      .send({
        client_name: 'Client without resource',
        redirect_uris: [REDIRECT_URI],
        grant_types: ['authorization_code'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    const clientId: string = registration.body.client_id;

    const consentPage = await openConsentPage(
      app,
      {
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        code_challenge: CODE_CHALLENGE,
        state: 'client-state',
        scope: 'offline_access',
      },
      OAUTH_FALLBACK_ENDPOINTS.authorize,
    );
    const providerRedirect = await submitConsent(app, consentPage, 'approve');
    const callback = await followProviderRedirect(
      app,
      // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
      providerRedirect.headers.location!,
      consentPage.cookie,
    );
    // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
    const code = new URL(callback.headers.location!).searchParams.get('code');

    const exchange = await request(app.getHttpServer()).post(OAUTH_FALLBACK_ENDPOINTS.token).send({
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      client_id: clientId,
      code_verifier: CODE_VERIFIER,
    });
    expect(exchange.status).toBe(200);

    const introspection = await request(app.getHttpServer()).post('/auth/introspect').send({
      token: exchange.body.access_token,
      client_id: clientId,
    });
    expect(introspection.status).toBe(200);
    expect(introspection.body.active).toBe(true);
    expect(introspection.body.resource).toBe(createMockModuleConfig().resource);
  });
});
