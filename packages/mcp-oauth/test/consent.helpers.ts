import assert from 'node:assert';
import type { INestApplication } from '@nestjs/common';
import request, { type Response } from 'supertest';
import { OAUTH_ENDPOINTS } from '../src';

export interface ConsentPage {
  response: Response;
  cookie: string;
  sessionId: string;
  csrfToken: string;
}

/** Opens the authorize endpoint like a browser does and reads what the consent form needs. */
export async function openConsentPage(
  app: INestApplication,
  query: Record<string, string>,
): Promise<ConsentPage> {
  const response = await request(app.getHttpServer())
    .get(OAUTH_ENDPOINTS.authorize)
    .query({ response_type: 'code', code_challenge_method: 'S256', ...query });
  assert.strictEqual(response.status, 200, `Expected the consent page, got ${response.status}`);

  const setCookie = response.headers['set-cookie'];
  const flowCookie = (Array.isArray(setCookie) ? setCookie : [setCookie]).find((value) =>
    value?.startsWith('mcp_oauth_flow_'),
  );
  assert.ok(flowCookie, 'The consent page sets a flow cookie');

  return {
    response,
    cookie: flowCookie.split(';')[0] ?? '',
    sessionId: hiddenField(response.text, 'session_id'),
    csrfToken: hiddenField(response.text, 'csrf_token'),
  };
}

export function submitConsent(
  app: INestApplication,
  page: ConsentPage,
  decision: 'approve' | 'deny',
  { cookie = page.cookie, csrfToken = page.csrfToken } = {},
) {
  const submission = request(app.getHttpServer())
    .post(OAUTH_ENDPOINTS.consent)
    .type('form')
    .send({ session_id: page.sessionId, csrf_token: csrfToken, decision });
  return cookie ? submission.set('Cookie', cookie) : submission;
}

/** Follows the provider redirect back to the callback, as the browser would after sign-in. */
export function followProviderRedirect(app: INestApplication, location: string, cookie?: string) {
  const providerRedirect = new URL(location);
  const callback = request(app.getHttpServer())
    .get(OAUTH_ENDPOINTS.callback)
    .query({
      state: providerRedirect.searchParams.get('state'),
      code: providerRedirect.searchParams.get('code'),
    });
  return cookie ? callback.set('Cookie', cookie) : callback;
}

function hiddenField(html: string, name: string): string {
  const value = new RegExp(`name="${name}" value="([^"]+)"`).exec(html)?.[1];
  assert.ok(value, `The consent page has a ${name} field`);
  return value;
}
