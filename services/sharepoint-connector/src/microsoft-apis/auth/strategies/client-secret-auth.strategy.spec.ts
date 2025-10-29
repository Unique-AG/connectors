import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../../../utils/redacted';
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

  const testScopes = ['https://graph.microsoft.com/.default'];

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
    const getTokenResult = {
      accessToken: 'test-token-123',
      expiresOn: expirationDate,
    };
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue(getTokenResult);

    const acquisitionResult = await strategy.acquireNewToken(testScopes);

    expect(acquisitionResult.token).toEqual(getTokenResult.accessToken);
    expect(acquisitionResult.expiresAt).toEqual(getTokenResult.expiresOn.getTime());
    expect(mockMsalClient.acquireTokenByClientCredential).toHaveBeenCalledWith({
      scopes: testScopes,
    });
  });

  it('throws error when no access token in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: null,
      expiresOn: new Date(),
    });

    await expect(strategy.acquireNewToken(testScopes)).rejects.toThrow(
      'Failed to acquire Graph API token: no access token in response',
    );
  });

  it('throws error when no expiration time in response', async () => {
    mockMsalClient.acquireTokenByClientCredential.mockResolvedValue({
      accessToken: 'test-token',
      expiresOn: null,
    });

    await expect(strategy.acquireNewToken(testScopes)).rejects.toThrow(
      'Failed to acquire Graph API token: no expiration time in response',
    );
  });

  it('throws error when SharePoint configuration is missing', () => {
    expect(
      () =>
        new ClientSecretAuthStrategy({
          get: vi.fn(() => undefined),
        } as never),
    ).toThrow();
  });
});
