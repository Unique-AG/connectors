import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';
import { openConsentPage } from './consent.helpers';

const CODE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
const REDIRECT_URI = 'http://localhost:4000/callback';
const DISCOVERY_PATHS = [
  '/.well-known/oauth-protected-resource',
  '/.well-known/oauth-protected-resource/mcp',
  '/.well-known/oauth-authorization-server',
];

/**
 * Runs against the module's real throttler. Every user of a tenant reaches the server from one
 * backend egress IP, and every user in an office from one NAT, so these limits must hold for
 * many users sharing an address, not just for one.
 */
describe('OAuth rate limits (E2E)', () => {
  let app: INestApplication;
  let clientId: string;

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [McpOAuthModule.forRootAsync({ useFactory: () => createMockModuleConfig() })],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    const registration = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Rate limit client',
        redirect_uris: [REDIRECT_URI],
        grant_types: ['authorization_code', 'refresh_token'],
        response_types: ['code'],
        token_endpoint_auth_method: 'none',
      });
    expect(registration.status).toBe(201);
    clientId = registration.body.client_id;
  });

  afterAll(async () => {
    await app.close();
  });

  it('serves discovery metadata to one IP without a limit', async () => {
    for (let attempt = 0; attempt < 25; attempt++) {
      for (const path of DISCOVERY_PATHS) {
        const response = await request(app.getHttpServer()).get(path);
        expect(response.status, `${path} on attempt ${attempt + 1}`).toBe(200);
      }
    }
  });

  it('lets more than ten users behind one IP open the consent page within a minute', async () => {
    for (let user = 0; user < 11; user++) {
      await openConsentPage(app, {
        client_id: clientId,
        redirect_uri: REDIRECT_URI,
        code_challenge: CODE_CHALLENGE,
        state: `state-${user}`,
        scope: 'offline_access',
      });
    }
  });

  it('lets one IP present more than ten different refresh tokens within a minute', async () => {
    for (let user = 0; user < 25; user++) {
      const response = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.token)
        .send({
          grant_type: 'refresh_token',
          refresh_token: `refresh-token-of-user-${user}`,
          client_id: clientId,
        });
      expect(response.status, `user ${user + 1}`).not.toBe(429);
    }
  });

  it('still limits one IP replaying the same refresh token', async () => {
    const statuses: number[] = [];
    for (let attempt = 0; attempt < 11; attempt++) {
      const response = await request(app.getHttpServer()).post(OAUTH_ENDPOINTS.token).send({
        grant_type: 'refresh_token',
        refresh_token: 'replayed-refresh-token',
        client_id: clientId,
      });
      statuses.push(response.status);
    }

    expect(statuses.slice(0, 10)).not.toContain(429);
    expect(statuses[10]).toBe(429);
  });
});
