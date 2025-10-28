import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../../utils/redacted';
import { ClientSecretAuthStrategy } from './client-secret-auth.strategy';

vi.mock('@azure/msal-node', () => ({
  ConfidentialClientApplication: vi.fn().mockImplementation(() => ({
    acquireTokenByClientCredential: vi.fn(),
  })),
}));

describe('ClientSecretAuthStrategy', () => {
  let strategy: ClientSecretAuthStrategy;
  let mockMsalClient: {
    acquireTokenByClientCredential: ReturnType<typeof vi.fn>;
  };

  const mockSharepointConfig = {
    authMode: 'client-secret' as const,
    authTenantId: 'tenant-123',
    authClientId: 'client-456',
    authClientSecret: new Redacted('secret-789'),
  };

  beforeEach(async () => {
    const { ConfidentialClientApplication } = await import('@azure/msal-node');
    mockMsalClient = {
      acquireTokenByClientCredential: vi.fn(),
    };
    vi.mocked(ConfidentialClientApplication).mockImplementation(() => mockMsalClient as never);

    const { unit } = await TestBed.solitary(ClientSecretAuthStrategy)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint') return mockSharepointConfig;
          return undefined;
        }),
      }))
      .compile();

    strategy = unit;
  });

  it('acquires a new token successfully', async () => {
    const expirationDate = new Date(Date.now() + 3600000);
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    });

    const token = await strategy.getAccessToken();

    expect(token).toBe('test-token-123');
    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledWith({
      scopes: ['https://graph.microsoft.com/.default'],
    });
  });

  it('returns cached token when still valid', async () => {
    const expirationDate = new Date(Date.now() + 3600000);
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    });

    await strategy.getAccessToken();
    const secondToken = await strategy.getAccessToken();

    expect(secondToken).toBe('test-token-123');
    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledTimes(1);
  });

  it('acquires new token when cached token expires', async () => {
    const expiredDate = new Date(Date.now() - 1000);
    const newExpirationDate = new Date(Date.now() + 3600000);

    mockMsalClient.acquireTokenByClientCredential
      .mockResolvedValueOnce({
        accessToken: 'expired-token',
        expiresOn: expiredDate,
      })
      .mockResolvedValueOnce({
        accessToken: 'new-token',
        expiresOn: newExpirationDate,
      });

    await strategy.getAccessToken();
    const newToken = await strategy.getAccessToken();

    expect(newToken).toBe('new-token');
    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledTimes(2);
  });

  it('throws error when no access token in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: null,
      expiresOn: new Date(),
    });

    await expect(strategy.getAccessToken()).rejects.toThrow(
      'Failed to acquire Graph API token: no access token in response',
    );
  });

  it('throws error when no expiration time in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token',
      expiresOn: null,
    });

    await expect(strategy.getAccessToken()).rejects.toThrow(
      'Failed to acquire Graph API token: no expiration time in response',
    );
  });

  it('caches tokens to avoid redundant MSAL calls', async () => {
    const expirationDate = new Date(Date.now() + 3600000);
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    });

    await strategy.getAccessToken();
    await strategy.getAccessToken();

    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledTimes(1);
  });

  it('throws error when SharePoint configuration is missing', () => {
    expect(
      () =>
        new ClientSecretAuthStrategy({
          get: vi.fn(() => undefined),
        } as never),
    ).toThrow();
  });

  it('clears cached token on authentication error', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockRejectedValue(
      new Error('Authentication failed'),
    );

    await expect(strategy.getAccessToken()).rejects.toThrow('Authentication failed');

    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'new-token',
      expiresOn: new Date(Date.now() + 3600000),
    });

    const token = await strategy.getAccessToken();
    expect(token).toBe('new-token');
  });
});
