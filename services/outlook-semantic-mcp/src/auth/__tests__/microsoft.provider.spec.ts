import type * as http from 'node:http';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  CALENDAR_SCOPES,
  createMicrosoftOAuthProvider,
  MAIL_SCOPES,
  resolveMicrosoftScopes,
} from '../microsoft.provider';

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

describe(resolveMicrosoftScopes.name, () => {
  it('produces a byte-identical mail-only scope string when calendar is disabled', () => {
    const scopes = resolveMicrosoftScopes(false);
    expect(scopes).toEqual(MAIL_SCOPES);
    expect(scopes.join(' ')).toBe(MAIL_SCOPES.join(' '));
    expect(scopes).not.toEqual(expect.arrayContaining(CALENDAR_SCOPES));
  });

  it('appends Calendars.ReadWrite.Shared when calendar is enabled', () => {
    const scopes = resolveMicrosoftScopes(true);
    expect(scopes).toEqual([...MAIL_SCOPES, ...CALENDAR_SCOPES]);
    expect(scopes).toContain('Calendars.ReadWrite.Shared');
  });
});
