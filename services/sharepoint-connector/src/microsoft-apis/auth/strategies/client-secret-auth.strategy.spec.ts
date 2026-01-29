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
    tenantId: 'tenant-123',
    auth: {
      mode: 'client-secret' as const,
      clientId: 'client-456',
      clientSecret: new Redacted('secret-789'),
    },
  };

  beforeEach(async () => {
    const { ConfidentialClientApplication } = await import('@azure/msal-node');
    mockMsalClient = {
      acquireTokenByClientCredential: vi.fn(),
    };
    vi.mocked(ConfidentialClientApplication).mockImplementation(() => mockMsalClient as never);

    const mockDispatcher = {};

    const { unitRef } = await TestBed.solitary(ClientSecretAuthStrategy)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint') return mockSharepointConfig;
          return undefined;
        }),
      }))
      .compile();

    // biome-ignore lint/suspicious/noExplicitAny: TestBed returns StubbedInstance, need cast for strategy constructor
    const configService = unitRef.get(ConfigService) as any;
    // biome-ignore lint/suspicious/noExplicitAny: Mock dispatcher for testing
    strategy = new ClientSecretAuthStrategy(configService, mockDispatcher as any);
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
    const mockDispatcher = {};
    expect(
      () =>
        new ClientSecretAuthStrategy(
          {
            get: vi.fn(() => undefined),
          } as never,
          mockDispatcher as never,
        ),
    ).toThrow();
  });
});
