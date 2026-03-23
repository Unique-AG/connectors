import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceAuth } from '../../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../../config';
import type { ProxyService } from '../../proxy';
import { ServiceRegistry } from '../../tenant/service-registry';
import { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { CloudConfluenceApiClient } from '../cloud-api-client';
import { ConfluenceApiClientFactory } from '../confluence-api-client.factory';
import { DataCenterConfluenceApiClient } from '../data-center-api-client';

vi.mock('../cloud-api-client', () => ({
  CloudConfluenceApiClient: vi.fn(),
}));
vi.mock('../data-center-api-client', () => ({
  DataCenterConfluenceApiClient: vi.fn(),
}));
vi.mock('../../utils/rate-limited-http-client', () => ({
  RateLimitedHttpClient: vi.fn(),
}));

const mockAuth = { acquireToken: vi.fn() } as unknown as ConfluenceAuth;

const mockServiceRegistry = {
  getService: vi.fn().mockReturnValue(mockAuth),
} as unknown as ServiceRegistry;

const mockProxyService = {
  getDispatcher: vi.fn().mockReturnValue({}),
} as unknown as ProxyService;

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

describe('ConfluenceApiClientFactory', () => {
  it('creates CloudConfluenceApiClient for cloud config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(RateLimitedHttpClient).toHaveBeenCalledWith(100, expect.anything());
    expect(CloudConfluenceApiClient).toHaveBeenCalledWith(
      config,
      mockAuth,
      expect.any(RateLimitedHttpClient),
      { attachmentsEnabled: false },
    );
  });

  it('creates DataCenterConfluenceApiClient for data-center config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = {
      ...baseFields,
      instanceType: 'data-center',
      auth: { mode: 'pat', token: { expose: () => 'tok' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(RateLimitedHttpClient).toHaveBeenCalledWith(100, expect.anything());
    expect(DataCenterConfluenceApiClient).toHaveBeenCalledWith(
      config,
      mockAuth,
      expect.any(RateLimitedHttpClient),
      { attachmentsEnabled: false },
    );
  });

  it('returns the created client instance', () => {
    const mockClient = {};
    vi.mocked(CloudConfluenceApiClient).mockImplementation(
      () => mockClient as unknown as CloudConfluenceApiClient,
    );
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    const result = factory.create(config);

    expect(result).toBe(mockClient);
  });
});
