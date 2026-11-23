import { describe, expect, it } from 'vitest';
import {
  authorizeTenant,
  CHAT_SCOPES,
  createMicrosoftOAuthProvider,
  IDENTITY_SCOPES,
  KB_SCOPES,
  MESSAGING_SCOPES,
  microsoftOAuthTokenUrl,
  resolveMicrosoftScopes,
  SCOPES,
} from './microsoft.provider';

function makeJwt(claims: Record<string, unknown>): string {
  const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return `eyJhbGciOiJSUzI1NiJ9.${payload}.fake-sig`;
}

describe(resolveMicrosoftScopes.name, () => {
  it('full mode (chat + ingestion) requests identity, messaging and KB scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'enabled', ingestion: 'enabled' });

    expect(scopes).toEqual(SCOPES);
    expect(scopes).toEqual([...CHAT_SCOPES, ...KB_SCOPES]);
    expect(scopes).toEqual([...IDENTITY_SCOPES, ...MESSAGING_SCOPES, ...KB_SCOPES]);
  });

  it('chat-only mode (chat, no ingestion) requests identity and messaging but no KB scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'enabled', ingestion: 'disabled' });

    expect(scopes).toEqual(CHAT_SCOPES);
    expect(scopes).toEqual([...IDENTITY_SCOPES, ...MESSAGING_SCOPES]);
    for (const kbScope of KB_SCOPES) {
      expect(scopes).not.toContain(kbScope);
    }
  });

  it('ingestion-only mode (ingestion, no chat) requests identity and KB but no messaging scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'disabled', ingestion: 'enabled' });

    expect(scopes).toEqual([...IDENTITY_SCOPES, ...KB_SCOPES]);
    for (const messagingScope of MESSAGING_SCOPES) {
      expect(scopes).not.toContain(messagingScope);
    }
    for (const kbScope of KB_SCOPES) {
      expect(scopes).toContain(kbScope);
    }
    for (const identityScope of IDENTITY_SCOPES) {
      expect(scopes).toContain(identityScope);
    }
  });

  it('both disabled requests only identity scopes', () => {
    const scopes = resolveMicrosoftScopes({ chat: 'disabled', ingestion: 'disabled' });

    expect(scopes).toEqual(IDENTITY_SCOPES);
    for (const messagingScope of MESSAGING_SCOPES) {
      expect(scopes).not.toContain(messagingScope);
    }
    for (const kbScope of KB_SCOPES) {
      expect(scopes).not.toContain(kbScope);
    }
  });
});

describe(createMicrosoftOAuthProvider.name, () => {
  const strategyArgs = {
    serverUrl: 'https://teams.mcp.example.com',
    clientId: 'client-id',
    clientSecret: 'client-secret',
    callbackPath: '/auth/callback',
  };

  it('passes tenant common in strategy options', () => {
    const provider = createMicrosoftOAuthProvider({
      chat: 'enabled',
      ingestion: 'disabled',
      signInTenantId: 'common',
    });

    expect(provider.strategyOptions(strategyArgs).tenant).toBe('common');
  });

  it('passes a pinned sign-in tenant id in strategy options', () => {
    const signInTenantId = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';
    const provider = createMicrosoftOAuthProvider({
      chat: 'disabled',
      ingestion: 'enabled',
      signInTenantId,
    });

    expect(provider.strategyOptions(strategyArgs).tenant).toBe(signInTenantId);
  });
});

describe(microsoftOAuthTokenUrl.name, () => {
  it('builds the v2 token URL for the given tenant', () => {
    expect(microsoftOAuthTokenUrl('common')).toBe(
      'https://login.microsoftonline.com/common/oauth2/v2.0/token',
    );
    expect(microsoftOAuthTokenUrl('f66cc3e7-9a7f-42ae-a0fa-adb72979b371')).toBe(
      'https://login.microsoftonline.com/f66cc3e7-9a7f-42ae-a0fa-adb72979b371/oauth2/v2.0/token',
    );
  });
});

describe(authorizeTenant.name, () => {
  const LISTED_TENANT = 'd050ee55-f842-4802-8263-d802dc017162';
  const OTHER_TENANT = '79a9ddfe-a4f3-4307-8086-471132901889';

  it('allows any tenant when the allowlist is empty', () => {
    expect(authorizeTenant(makeJwt({ tid: OTHER_TENANT }), [])).toEqual({ allowed: true });
  });

  it('allows a tenant on the allowlist', () => {
    expect(authorizeTenant(makeJwt({ tid: LISTED_TENANT }), [LISTED_TENANT])).toEqual({
      allowed: true,
    });
  });

  it('rejects a tenant not on the allowlist and names it in the reason', () => {
    expect(authorizeTenant(makeJwt({ tid: OTHER_TENANT }), [LISTED_TENANT])).toEqual({
      allowed: false,
      reason: `Entra tenant ${OTHER_TENANT} is not on the allowlist`,
    });
  });

  it('throws for a token without a tid claim', () => {
    expect(() => authorizeTenant(makeJwt({ sub: 'user' }), [LISTED_TENANT])).toThrow(
      'Access token has no tid claim',
    );
  });

  it('rejects the sign-in of a user from a tenant not on the allowlist', () => {
    const provider = createMicrosoftOAuthProvider({
      chat: 'enabled',
      ingestion: 'disabled',
      signInTenantId: 'common',
      allowedTenantIds: [LISTED_TENANT],
    });

    expect(
      provider.authorizeSignIn?.({ accessToken: makeJwt({ tid: OTHER_TENANT }), profile: {} }),
    ).toEqual({ allowed: false, reason: `Entra tenant ${OTHER_TENANT} is not on the allowlist` });
  });
});
