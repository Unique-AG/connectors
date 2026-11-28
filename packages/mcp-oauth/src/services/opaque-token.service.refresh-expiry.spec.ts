import assert from 'node:assert';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockOAuthStore } from '../__mocks__/oauth-store.mock';
import type { McpOAuthModuleOptions } from '../mcp-oauth.module-definition';
import { OpaqueTokenService } from './opaque-token.service';

const HOUR_MS = 60 * 60 * 1000;
const SIGN_IN_AT = new Date('2026-11-26T08:00:00Z');

const serviceWith = (refreshTokenExpiry: McpOAuthModuleOptions['refreshTokenExpiry']) => {
  const store = new MockOAuthStore();
  const options = {
    accessTokenExpiresIn: 60,
    refreshTokenExpiresIn: 3600,
    refreshTokenExpiry,
  } as McpOAuthModuleOptions;
  return { store, service: new OpaqueTokenService(options, store) };
};

// Signs in, then rotates the refresh token twice, 20 minutes apart.
async function rotateTwice(refreshTokenExpiry: McpOAuthModuleOptions['refreshTokenExpiry']) {
  const { store, service } = serviceWith(refreshTokenExpiry);
  const first = await service.generateTokenPair('user-1', 'client-1', 'mail', 'r', 'profile-1');

  vi.setSystemTime(SIGN_IN_AT.getTime() + HOUR_MS / 3);
  const second = await service.refreshAccessToken(first.refresh_token, 'client-1');
  assert.ok(second);
  vi.setSystemTime(SIGN_IN_AT.getTime() + (2 * HOUR_MS) / 3);
  const third = await service.refreshAccessToken(second.refresh_token, 'client-1');
  assert.ok(third);

  const expiryOf = async (token: string) => (await store.getRefreshToken(token))?.expiresAt;
  return { store, service, third, expiryOf };
}

describe('OpaqueTokenService refresh token expiry', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(SIGN_IN_AT);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('absolute', () => {
    it('gives a rotated refresh token the expiry of the first one', async () => {
      const { third, expiryOf } = await rotateTwice('absolute');

      expect(await expiryOf(third.refresh_token)).toEqual(new Date(SIGN_IN_AT.getTime() + HOUR_MS));
    });

    it('issues no access token that outlives the session', async () => {
      const { service, store, third } = await rotateTwice('absolute');
      vi.setSystemTime(SIGN_IN_AT.getTime() + HOUR_MS - 30_000);

      const last = await service.refreshAccessToken(third.refresh_token, 'client-1');

      assert.ok(last);
      expect(last.expires_in).toBe(30);
      expect((await store.getAccessToken(last.access_token))?.expiresAt).toEqual(
        new Date(SIGN_IN_AT.getTime() + HOUR_MS),
      );
    });

    it('rejects the refresh token once the session has expired', async () => {
      const { service, third } = await rotateTwice('absolute');
      vi.setSystemTime(SIGN_IN_AT.getTime() + HOUR_MS + 1);

      expect(await service.refreshAccessToken(third.refresh_token, 'client-1')).toBeNull();
    });
  });

  describe('sliding', () => {
    it('gives a rotated refresh token the full lifetime from its rotation', async () => {
      const { third, expiryOf } = await rotateTwice('sliding');

      expect(await expiryOf(third.refresh_token)).toEqual(
        new Date(SIGN_IN_AT.getTime() + (2 * HOUR_MS) / 3 + HOUR_MS),
      );
      expect(third.expires_in).toBe(60);
    });

    it('keeps the configured access token lifetime when it is longer than the refresh lifetime', async () => {
      const store = new MockOAuthStore();
      const service = new OpaqueTokenService(
        {
          accessTokenExpiresIn: 3600,
          refreshTokenExpiresIn: 60,
          refreshTokenExpiry: 'sliding',
        } as McpOAuthModuleOptions,
        store,
      );

      const pair = await service.generateTokenPair('user-1', 'client-1', 'mail', 'r', 'profile-1');

      expect(pair.expires_in).toBe(3600);
      expect((await store.getAccessToken(pair.access_token))?.expiresAt).toEqual(
        new Date(SIGN_IN_AT.getTime() + HOUR_MS),
      );
    });
  });
});
