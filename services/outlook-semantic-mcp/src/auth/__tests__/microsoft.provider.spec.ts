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

import { createMicrosoftOAuthProvider, getScopes } from '../microsoft.provider';

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
