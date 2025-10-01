import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphAuthenticationProvider } from './graph-authentication.service';

vi.mock('@azure/msal-node', () => ({
  ConfidentialClientApplication: vi.fn().mockImplementation(() => ({
    acquireTokenByClientCredential: vi.fn(),
  })),
}));

describe('GraphAuthenticationProvider', () => {
  let provider: GraphAuthenticationProvider;
  let mockMsalClient: {
    acquireTokenByClientCredential: ReturnType<typeof vi.fn>;
  };

  const mockConfig = {
    'sharepoint.tenantId': 'tenant-123',
    'sharepoint.clientId': 'client-456',
    'sharepoint.clientSecret': 'secret-789',
  };

  beforeEach(async () => {
    const { ConfidentialClientApplication } = await import('@azure/msal-node');
    mockMsalClient = {
      acquireTokenByClientCredential: vi.fn(),
    };
    vi.mocked(ConfidentialClientApplication).mockImplementation(() => mockMsalClient as never);

    const { unit } = await TestBed.solitary(GraphAuthenticationProvider)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => mockConfig[key as keyof typeof mockConfig]),
      }))
      .compile();

    provider = unit;
  });

  it('acquires a new token successfully', async () => {
    const expirationDate = new Date(Date.now() + 3600000);
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    });

    const token = await provider.getAccessToken();

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

    await provider.getAccessToken();
    const secondToken = await provider.getAccessToken();

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

    await provider.getAccessToken();
    const newToken = await provider.getAccessToken();

    expect(newToken).toBe('new-token');
    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledTimes(2);
  });

  it('throws error when no access token in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: null,
      expiresOn: new Date(),
    });

    await expect(provider.getAccessToken()).rejects.toThrow(
      'Failed to acquire Graph API token: no access token in response',
    );
  });

  it('throws error when no expiration time in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token',
      expiresOn: null,
    });

    await expect(provider.getAccessToken()).rejects.toThrow(
      'Failed to acquire Graph API token: no expiration time in response',
    );
  });

  it('clears token cache', async () => {
    const expirationDate = new Date(Date.now() + 3600000);
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    });

    await provider.getAccessToken();
    provider.clearTokenCache();
    await provider.getAccessToken();

    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledTimes(2);
  });

  it('throws error when SharePoint configuration is missing', () => {
    expect(
      () =>
        new GraphAuthenticationProvider({
          get: vi.fn(() => undefined),
        } as never),
    ).toThrow('SharePoint configuration missing: tenantId, clientId, and clientSecret are required');
  });

  it('clears cached token on authentication error', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockRejectedValue(
      new Error('Authentication failed'),
    );

    await expect(provider.getAccessToken()).rejects.toThrow('Authentication failed');

    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'new-token',
      expiresOn: new Date(Date.now() + 3600000),
    });

    const token = await provider.getAccessToken();
    expect(token).toBe('new-token');
  });
});

