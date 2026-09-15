import { GraphError } from '@microsoft/microsoft-graph-client';
import { describe, expect, it } from 'vitest';
import { isAppLevelOAuthError } from '../is-app-level-oauth-error';

describe(isAppLevelOAuthError.name, () => {
  it.each([
    ['invalid_client', true],
    ['unauthorized_client', true],
    ['invalid_grant', false],
    ['interaction_required', false],
    ['consent_required', false],
    ['temporarily_unavailable', false],
  ] as const)('classifies OAuth error code %s as app-level=%s', (code, expected) => {
    expect(isAppLevelOAuthError(code)).toBe(expected);
    expect(isAppLevelOAuthError({ error: code })).toBe(expected);
  });

  it('does not treat HTTP 429 or 5xx as app-level', () => {
    const tooManyRequests = new GraphError(429, 'Too Many Requests');
    tooManyRequests.statusCode = 429;
    const serverError = new GraphError(503, 'Service Unavailable');
    serverError.statusCode = 503;

    expect(isAppLevelOAuthError(429)).toBe(false);
    expect(isAppLevelOAuthError(503)).toBe(false);
    expect(isAppLevelOAuthError({ status: 429 })).toBe(false);
    expect(isAppLevelOAuthError({ status: 500 })).toBe(false);
    expect(isAppLevelOAuthError(tooManyRequests)).toBe(false);
    expect(isAppLevelOAuthError(serverError)).toBe(false);
  });

  it('returns false for empty or unrelated values', () => {
    expect(isAppLevelOAuthError(undefined)).toBe(false);
    expect(isAppLevelOAuthError(null)).toBe(false);
    expect(isAppLevelOAuthError({})).toBe(false);
    expect(isAppLevelOAuthError(new Error('network error'))).toBe(false);
  });
});
