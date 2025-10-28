import { DefaultAzureCredential } from '@azure/identity';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OidcAuthStrategy } from './oidc-auth.strategy';

vi.mock('@azure/identity', () => ({
  DefaultAzureCredential: vi.fn().mockImplementation(() => ({
    getToken: vi.fn(),
  })),
}));

describe('OidcAuthStrategy', () => {
  let strategy: OidcAuthStrategy;
  let mockCredential: {
    getToken: ReturnType<typeof vi.fn>;
  };

  const testScopes = ['https://graph.microsoft.com/.default'];

  const mockSharepointConfig = {
    authMode: 'oidc' as const,
    authTenantId: 'tenant-123',
  };

  beforeEach(async () => {
    mockCredential = {
      getToken: vi.fn(),
    };
    vi.mocked(DefaultAzureCredential).mockImplementation(() => mockCredential as never);

    const { unit } = await TestBed.solitary(OidcAuthStrategy)
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
    const expiresOnTimestamp = Date.now() + 3600 * 1000; // 1 hour from now in milliseconds
    const getTokenResult = {
      token: 'test-token-123',
      expiresOnTimestamp,
    };
    mockCredential.getToken.mockResolvedValue(getTokenResult);

    const acquisitionResult = await strategy.acquireNewToken(testScopes);

    expect(acquisitionResult.token).toEqual(getTokenResult.token);
    expect(acquisitionResult.expiresAt).toEqual(getTokenResult.expiresOnTimestamp);
    expect(mockCredential.getToken).toHaveBeenCalledWith(testScopes);
  });

  it('throws error when no access token in response', async () => {
    mockCredential.getToken.mockResolvedValue({
      token: null,
      expiresOnTimestamp: Date.now() + 3600 * 1000,
    });

    await expect(strategy.acquireNewToken(testScopes)).rejects.toThrow();
  });

  it('throws error when no expiration time in response', async () => {
    mockCredential.getToken.mockResolvedValue({
      token: 'test-token',
      expiresOnTimestamp: null,
    });

    await expect(strategy.acquireNewToken(testScopes)).rejects.toThrow();
  });
});
