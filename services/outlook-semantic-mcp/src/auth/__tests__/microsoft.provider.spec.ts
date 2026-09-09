import type * as http from 'node:http';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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
