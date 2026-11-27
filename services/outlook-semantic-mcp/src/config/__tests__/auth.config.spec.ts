import { afterEach, describe, expect, it, vi } from 'vitest';
import { authConfig } from '../auth.config';

const loadWith = (env: Record<string, string | undefined>) => {
  for (const key of Object.keys(process.env).filter((key) => key.startsWith('AUTH_'))) {
    vi.stubEnv(key, undefined);
  }
  vi.stubEnv('MICROSOFT_OFFLINE_ACCESS', undefined);
  vi.stubEnv('AUTH_HMAC_SECRET', 'h'.repeat(64));
  for (const [key, value] of Object.entries(env)) {
    vi.stubEnv(key, value);
  }
  return authConfig();
};

describe('authConfig', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('keeps a sliding refresh expiry with offline access on', async () => {
    await expect(loadWith({})).resolves.toMatchObject({
      refreshTokenExpiresInSeconds: 2592000,
      refreshTokenExpiry: 'sliding',
    });
  });

  it('ends the session an hour after sign-in with offline access off', async () => {
    await expect(
      loadWith({
        MICROSOFT_OFFLINE_ACCESS: 'disabled',
        AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS: '3600',
      }),
    ).resolves.toMatchObject({
      refreshTokenExpiresInSeconds: 3600,
      refreshTokenExpiry: 'absolute',
    });
  });

  it('throws naming AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS when the session outlasts an hour with offline access off', async () => {
    await expect(loadWith({ MICROSOFT_OFFLINE_ACCESS: 'disabled' })).rejects.toThrow(
      'AUTH_REFRESH_TOKEN_EXPIRES_IN_SECONDS must be at most 3600 with MICROSOFT_OFFLINE_ACCESS=disabled',
    );
  });
});
