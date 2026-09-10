import type { OpaqueTokenService } from '@unique-ag/mcp-oauth';
import { Client } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphClientFactory } from '../graph-client.factory';

const mockDispatcher = { kind: 'proxy-dispatcher' };

const mockGetDispatcher = vi.fn().mockReturnValue(mockDispatcher);

vi.mock('@microsoft/microsoft-graph-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@microsoft/microsoft-graph-client')>();
  return {
    ...actual,
    Client: {
      ...actual.Client,
      initWithMiddleware: vi.fn().mockReturnValue({ api: vi.fn() }),
    },
  };
});

vi.mock('../token.provider', () => ({
  TokenProvider: vi.fn(class MockTokenProvider {}),
}));

import { TokenProvider } from '../token.provider';

describe('GraphClientFactory', () => {
  const mockConfigService = {
    get: vi.fn((key: string) => {
      if (key === 'microsoft.clientId') {
        return 'test-client-id';
      }
      if (key === 'microsoft.clientSecret') {
        return { value: 'test-client-secret' };
      }
      if (key === 'microsoft.signInTenantId') {
        return 'common';
      }
      if (key === 'app.isDebuggingOn') {
        return false;
      }
      return undefined;
    }),
  };

  const mockProxyService = {
    getDispatcher: mockGetDispatcher,
  };

  const mockMetricService = {
    getCounter: vi.fn().mockReturnValue({ add: vi.fn() }),
    getHistogram: vi.fn().mockReturnValue({ record: vi.fn() }),
  };

  const mockOpaqueTokenService: Pick<OpaqueTokenService, 'revokeAllTokensForUserProfile'> = {
    revokeAllTokensForUserProfile: vi.fn().mockResolvedValue(undefined),
  };

  let factory: GraphClientFactory;

  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDispatcher.mockReturnValue(mockDispatcher);

    factory = new GraphClientFactory(
      mockConfigService as never,
      {} as never,
      {} as never,
      mockMetricService as never,
      mockProxyService as never,
      mockOpaqueTokenService as never,
    );
  });

  it('wires onPermanentAuthFailure to revoke every MCP token for the profile', async () => {
    factory.createClientForUser('user-profile-123');

    expect(TokenProvider).toHaveBeenCalledTimes(1);
    // biome-ignore lint/style/noNonNullAssertion: tested for existence with expect
    const [, dependencies] = vi.mocked(TokenProvider).mock.calls[0]!;
    await dependencies.onPermanentAuthFailure?.('user-profile-123');

    expect(mockOpaqueTokenService.revokeAllTokensForUserProfile).toHaveBeenCalledWith(
      'user-profile-123',
    );
  });

  it('passes proxy dispatcher to Client.initWithMiddleware in always mode', () => {
    factory.createClientForUser('user-profile-123');

    expect(mockGetDispatcher).toHaveBeenCalledWith({ mode: 'always' });
    expect(Client.initWithMiddleware).toHaveBeenCalledWith(
      expect.objectContaining({
        fetchOptions: { dispatcher: mockDispatcher },
        debugLogging: false,
      }),
    );
  });

  it('passes proxy dispatcher to TokenProvider in always mode', () => {
    factory.createClientForUser('user-profile-123');

    expect(mockGetDispatcher).toHaveBeenCalledWith({ mode: 'always' });
    expect(TokenProvider).toHaveBeenCalledWith(
      expect.objectContaining({
        userProfileId: 'user-profile-123',
        clientId: 'test-client-id',
        clientSecret: 'test-client-secret',
        signInTenantId: 'common',
      }),
      expect.objectContaining({
        dispatcher: mockDispatcher,
      }),
    );
  });
});
