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

import { createMicrosoftOAuthProvider } from '../microsoft.provider';

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
