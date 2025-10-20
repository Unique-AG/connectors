import { DefaultAzureCredential } from '@azure/identity';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OidcGraphAuthStrategy } from './oidc-graph-auth.strategy';

vi.mock('@azure/identity', () => ({
  DefaultAzureCredential: vi.fn().mockImplementation(() => ({
    getToken: vi.fn(),
  })),
}));

describe('OidcGraphAuthStrategy', () => {
  let strategy: OidcGraphAuthStrategy;
  let mockCredential: {
    getToken: ReturnType<typeof vi.fn>;
  };

  const mockConfig = {
    'sharepoint.tenantId': 'tenant-123',
    'sharepoint.clientId': 'client-456',
  };

  beforeEach(async () => {
    mockCredential = {
      getToken: vi.fn(),
    };
    vi.mocked(DefaultAzureCredential).mockImplementation(() => mockCredential as never);

    const { unit } = await TestBed.solitary(OidcGraphAuthStrategy)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => mockConfig[key as keyof typeof mockConfig]),
      }))
      .compile();

    strategy = unit;
  });

  it('acquires a new token successfully', async () => {
    const expiresOnTimestamp = Date.now() + 3600 * 1000; // 1 hour from now in milliseconds
    mockCredential.getToken.mockResolvedValue({
      token: 'test-token-123',
      expiresOnTimestamp,
    });

    const token = await strategy.getAccessToken('https://graph.microsoft.com/.default');

    expect(token).toBe('test-token-123');
    expect(mockCredential.getToken).toHaveBeenCalledWith('https://graph.microsoft.com/.default');
  });

  it('returns cached token when still valid', async () => {
    const expiresOnTimestamp = Date.now() + 3600 * 1000; // 1 hour from now in milliseconds
    mockCredential.getToken.mockResolvedValue({
      token: 'test-token-123',
      expiresOnTimestamp,
    });

    await strategy.getAccessToken('https://graph.microsoft.com/.default');
    const secondToken = await strategy.getAccessToken('https://graph.microsoft.com/.default');

    expect(secondToken).toBe('test-token-123');
    expect(mockCredential.getToken).toHaveBeenCalledTimes(1);
  });

  it('throws error when no access token in response', async () => {
    mockCredential.getToken.mockResolvedValue({
      token: null,
      expiresOnTimestamp: Date.now() + 3600 * 1000,
    });

    await expect(strategy.getAccessToken('https://graph.microsoft.com/.default')).rejects.toThrow();
  });

  it('throws error when no expiration time in response', async () => {
    mockCredential.getToken.mockResolvedValue({
      token: 'test-token',
      expiresOnTimestamp: null,
    });

    await expect(strategy.getAccessToken('https://graph.microsoft.com/.default')).rejects.toThrow();
  });

  it('clears cached token on authentication error', async () => {
    mockCredential.getToken.mockRejectedValue(new Error('Authentication failed'));

    await expect(strategy.getAccessToken('https://graph.microsoft.com/.default')).rejects.toThrow('Authentication failed');

    const expiresOnTimestamp = Date.now() + 3600 * 1000;
    mockCredential.getToken.mockResolvedValue({
      token: 'new-token',
      expiresOnTimestamp,
    });

    const token = await strategy.getAccessToken('https://graph.microsoft.com/.default');
    expect(token).toBe('new-token');
  });
});
