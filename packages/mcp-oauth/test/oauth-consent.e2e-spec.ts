import { type INestApplication } from '@nestjs/common';
import { Test, type TestingModule } from '@nestjs/testing';
import { ThrottlerGuard } from '@nestjs/throttler';
import request from 'supertest';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { OAUTH_ENDPOINTS } from '../src';
import { createMockModuleConfig, MockOAuthStore } from '../src/__mocks__';
import { McpOAuthModule } from '../src/mcp-oauth.module';
import {
  type ConsentPage,
  followProviderRedirect,
  openConsentPage,
  submitConsent,
} from './consent.helpers';

const REDIRECT_URI = 'https://attacker.example/oauth/callback';
const CODE_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
const CLIENT_STATE = 'client-state-123';

describe('OAuth consent (E2E)', () => {
  let app: INestApplication;
  let oauthStore: MockOAuthStore;
  let clientId: string;

  beforeAll(async () => {
    const config = createMockModuleConfig();
    oauthStore = config.oauthStore as MockOAuthStore;

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [McpOAuthModule.forRootAsync({ useFactory: () => config })],
    })
      .overrideGuard(ThrottlerGuard)
      .useValue({ canActivate: () => true })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();

    const registration = await request(app.getHttpServer())
      .post(OAUTH_ENDPOINTS.register)
      .send({
        client_name: 'Totally <b>Legit</b> Client',
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

  beforeEach(() => {
    oauthStore.clearDynamicData();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const openPage = () =>
    openConsentPage(app, {
      client_id: clientId,
      redirect_uri: REDIRECT_URI,
      code_challenge: CODE_CHALLENGE,
      state: CLIENT_STATE,
      scope: 'offline_access',
    });

  describe('GET /auth/authorize', () => {
    let page: ConsentPage;

    beforeEach(async () => {
      page = await openPage();
    });

    it('returns the consent page instead of redirecting to the provider', () => {
      expect(page.response.status).toBe(200);
      expect(page.response.headers.location).toBeUndefined();
      expect(page.response.headers['content-type']).toBe('text/html; charset=utf-8');
    });

    it('names the client, escaped, and shows the redirect host', () => {
      expect(page.response.text).toContain('Totally &lt;b&gt;Legit&lt;/b&gt; Client');
      expect(page.response.text).not.toContain('<b>Legit</b>');
      expect(page.response.text).toContain('<strong>attacker.example</strong>');
    });

    it('sends a strict CSP and forbids framing', () => {
      expect(page.response.headers['content-security-policy']).toBe(
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
      );
      expect(page.response.headers['x-frame-options']).toBe('DENY');
      expect(page.response.headers['cache-control']).toBe('no-store');
    });

    it('sets an HttpOnly SameSite=Lax flow cookie', () => {
      const setCookie = [page.response.headers['set-cookie']].flat().join('\n');

      expect(setCookie).toMatch(/mcp_oauth_flow_[0-9a-f]{16}=/);
      expect(setCookie).toContain('HttpOnly');
      expect(setCookie).toContain('SameSite=Lax');
      expect(setCookie).toContain('Path=/');
    });
  });

  describe('POST /auth/consent', () => {
    it('redirects to the provider when approved with the flow cookie and CSRF token', async () => {
      const page = await openPage();

      const response = await submitConsent(app, page, 'approve');

      expect(response.status).toBe(302);
      expect(response.headers.location).toMatch(
        /^http:\/\/mock-idp-server\.example\/auth\/callback/,
      );
    });

    it('rejects an approval without the flow cookie', async () => {
      const page = await openPage();

      const response = await submitConsent(app, page, 'approve', { cookie: '' });

      expect(response.status).toBe(403);
      expect(response.headers.location).toBeUndefined();
    });

    it('rejects an approval with a flow cookie from another flow', async () => {
      const victimPage = await openPage();
      const attackerPage = await openPage();

      const response = await submitConsent(app, victimPage, 'approve', {
        cookie: attackerPage.cookie.replace(/^[^=]+/, victimPage.cookie.split('=')[0] ?? ''),
      });

      expect(response.status).toBe(403);
    });

    it('rejects an approval with a bad CSRF token', async () => {
      const page = await openPage();

      const response = await submitConsent(app, page, 'approve', { csrfToken: 'forged' });

      expect(response.status).toBe(403);
    });

    it('rejects an unknown decision', async () => {
      const page = await openPage();

      const response = await request(app.getHttpServer())
        .post(OAUTH_ENDPOINTS.consent)
        .set('Cookie', page.cookie)
        .type('form')
        .send({ session_id: page.sessionId, csrf_token: page.csrfToken, decision: 'maybe' });

      expect(response.status).toBe(400);
    });

    it('is not reachable with GET', async () => {
      const page = await openPage();

      const response = await request(app.getHttpServer())
        .get(OAUTH_ENDPOINTS.consent)
        .set('Cookie', page.cookie)
        .query({ session_id: page.sessionId, csrf_token: page.csrfToken, decision: 'approve' });

      expect(response.status).toBe(404);
    });

    it('redirects to the client with access_denied and its state when denied', async () => {
      const page = await openPage();

      const response = await submitConsent(app, page, 'deny');

      expect(response.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const location = new URL(response.headers.location!);
      expect(`${location.origin}${location.pathname}`).toBe(REDIRECT_URI);
      expect(location.searchParams.get('error')).toBe('access_denied');
      expect(location.searchParams.get('state')).toBe(CLIENT_STATE);
      expect(location.searchParams.has('code')).toBe(false);
      expect(await oauthStore.getOAuthSession(page.sessionId)).toBeUndefined();
    });
  });

  describe('GET /auth/callback', () => {
    it('issues a code to the browser that started and approved the flow', async () => {
      const page = await openPage();
      const approval = await submitConsent(app, page, 'approve');

      // biome-ignore lint/style/noNonNullAssertion: approval redirects
      const response = await followProviderRedirect(app, approval.headers.location!, page.cookie);

      expect(response.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const location = new URL(response.headers.location!);
      expect(location.searchParams.get('code')).toEqual(expect.any(String));
      expect(location.searchParams.get('state')).toBe(CLIENT_STATE);
    });

    it('signs in when the user submits the approval twice', async () => {
      const page = await openPage();
      const first = await submitConsent(app, page, 'approve');
      const second = await submitConsent(app, page, 'approve');

      expect(second.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const secondState = new URL(second.headers.location!).searchParams.get('state');
      // biome-ignore lint/style/noNonNullAssertion: approval redirects
      expect(new URL(first.headers.location!).searchParams.get('state')).toBe(secondState);

      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const response = await followProviderRedirect(app, second.headers.location!, page.cookie);

      expect(response.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      expect(new URL(response.headers.location!).searchParams.get('code')).toEqual(
        expect.any(String),
      );
    });

    it('signs in when two approvals arrive at the same time', async () => {
      const page = await openPage();
      const approvals = await Promise.all([
        submitConsent(app, page, 'approve'),
        submitConsent(app, page, 'approve'),
      ]);

      expect(approvals.map(({ status }) => status)).toEqual([302, 302]);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const [first, last] = approvals.map(({ headers }) => new URL(headers.location!));
      expect(last?.searchParams.get('state')).toBe(first?.searchParams.get('state'));

      const response = await followProviderRedirect(app, String(last), page.cookie);

      expect(response.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      expect(new URL(response.headers.location!).searchParams.get('code')).toEqual(
        expect.any(String),
      );
    });

    it('rejects a provider redirect followed in a browser without the flow cookie', async () => {
      const attackerPage = await openPage();
      const approval = await submitConsent(app, attackerPage, 'approve');
      const upsertUserProfile = vi.spyOn(oauthStore, 'upsertUserProfile');
      const storeAuthCode = vi.spyOn(oauthStore, 'storeAuthCode');

      // biome-ignore lint/style/noNonNullAssertion: approval redirects
      const response = await followProviderRedirect(app, approval.headers.location!);

      expect(response.status).toBe(401);
      expect(response.headers.location).toBeUndefined();
      expect(upsertUserProfile).not.toHaveBeenCalled();
      expect(storeAuthCode).not.toHaveBeenCalled();
    });

    it('rejects a callback for a flow nobody approved', async () => {
      const page = await openPage();
      const forgedState = Buffer.from(
        JSON.stringify({ sessionId: page.sessionId, sessionNonce: 'n', sessionHmac: 'h' }),
      ).toString('base64url');

      const response = await request(app.getHttpServer())
        .get(OAUTH_ENDPOINTS.callback)
        .set('Cookie', page.cookie)
        .query({ state: forgedState, code: 'mock-provider-code' });

      expect(response.status).toBe(302);
      // biome-ignore lint/style/noNonNullAssertion: asserted by the 302
      const location = new URL(response.headers.location!);
      expect(location.searchParams.get('error')).toBe('access_denied');
      expect(location.searchParams.has('code')).toBe(false);
    });
  });
});
