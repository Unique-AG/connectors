import type * as http from 'node:http';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function makeJwt(claims: Record<string, unknown>): string {
  const payload = Buffer.from(JSON.stringify(claims)).toString('base64url');
  return `eyJhbGciOiJSUzI1NiJ9.${payload}.fake-sig`;
}

const { setAgentMock } = vi.hoisted(() => ({
  setAgentMock: vi.fn(),
}));

vi.mock('passport-microsoft', () => {
  class MockMicrosoft {
    public _oauth2 = { setAgent: setAgentMock };
    public constructor() {}
  }
  return { Strategy: MockMicrosoft };
});

import {
  authorizeTenant,
  createMicrosoftOAuthProvider,
  getScopes,
  microsoftOAuthTokenUrl,
} from '../microsoft.provider';

const MAIL_ONLY_SCOPE_STRING =
  'openid profile email offline_access User.Read User.Read.All MailboxSettings.Read Mail.ReadWrite Mail.ReadWrite.Shared People.Read';

describe('createMicrosoftOAuthProvider', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls setAgent when an agent is provided', () => {
    const agent = {} as http.Agent;
    const provider = createMicrosoftOAuthProvider(agent);
    const Strategy = provider.strategy as new (...args: unknown[]) => unknown;

    new Strategy();

    expect(setAgentMock).toHaveBeenCalledOnce();
    expect(setAgentMock).toHaveBeenCalledWith(agent);
  });

  it('does not call setAgent when agent is undefined', () => {
    const provider = createMicrosoftOAuthProvider(undefined);
    const Strategy = provider.strategy as new (...args: unknown[]) => unknown;

    new Strategy();

    expect(setAgentMock).not.toHaveBeenCalled();
  });

  const strategyArgs = {
    serverUrl: 'https://outlook.semantic.mcp.example.com',
    clientId: 'client-id',
    clientSecret: 'client-secret',
    callbackPath: '/auth/callback',
  };

  it('passes tenant common in strategy options by default', () => {
    const provider = createMicrosoftOAuthProvider();

    expect(provider.strategyOptions(strategyArgs).tenant).toBe('common');
  });

  it('passes a pinned sign-in tenant id in strategy options', () => {
    const signInTenantId = 'f66cc3e7-9a7f-42ae-a0fa-adb72979b371';
    const provider = createMicrosoftOAuthProvider(undefined, signInTenantId);

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
    const provider = createMicrosoftOAuthProvider(undefined, 'common', [LISTED_TENANT]);

    expect(
      provider.authorizeSignIn?.({ accessToken: makeJwt({ tid: OTHER_TENANT }), profile: {} }),
    ).toEqual({ allowed: false, reason: `Entra tenant ${OTHER_TENANT} is not on the allowlist` });
  });
});

describe(getScopes.name, () => {
  const original = process.env.CALENDAR_INTEGRATION;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.CALENDAR_INTEGRATION;
    } else {
      process.env.CALENDAR_INTEGRATION = original;
    }
  });

  it('returns the mail-only scope string when CALENDAR_INTEGRATION is unset', () => {
    delete process.env.CALENDAR_INTEGRATION;
    expect(getScopes().join(' ')).toBe(MAIL_ONLY_SCOPE_STRING);
  });

  it('returns the mail-only scope string when CALENDAR_INTEGRATION=disabled', () => {
    process.env.CALENDAR_INTEGRATION = 'disabled';
    expect(getScopes().join(' ')).toBe(MAIL_ONLY_SCOPE_STRING);
  });

  it('appends Calendars.ReadWrite.Shared when CALENDAR_INTEGRATION=enabled', () => {
    process.env.CALENDAR_INTEGRATION = 'enabled';
    expect(getScopes().join(' ')).toBe(`${MAIL_ONLY_SCOPE_STRING} Calendars.ReadWrite.Shared`);
  });
});
