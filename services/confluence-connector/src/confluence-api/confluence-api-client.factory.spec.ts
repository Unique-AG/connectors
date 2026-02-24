import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceAuth } from '../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../config';
import { ServiceRegistry } from '../tenant/service-registry';
import { CloudConfluenceApiClient } from './cloud-api-client';
import { ConfluenceApiClientFactory } from './confluence-api-client.factory';
import { DataCenterConfluenceApiClient } from './data-center-api-client';

vi.mock('./cloud-api-client', () => ({
  CloudConfluenceApiClient: vi.fn(),
}));
vi.mock('./data-center-api-client', () => ({
  DataCenterConfluenceApiClient: vi.fn(),
}));

const mockAuth = { acquireToken: vi.fn() } as unknown as ConfluenceAuth;
const mockLogger = { info: vi.fn(), warn: vi.fn(), error: vi.fn() };

const mockServiceRegistry = {
  getService: vi.fn().mockReturnValue(mockAuth),
  getServiceLogger: vi.fn().mockReturnValue(mockLogger),
} as unknown as ServiceRegistry;

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

describe('ConfluenceApiClientFactory', () => {
  it('creates CloudConfluenceApiClient for cloud config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(CloudConfluenceApiClient).toHaveBeenCalledWith(config, mockAuth, mockLogger);
  });

  it('creates DataCenterConfluenceApiClient for data-center config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'data-center',
      auth: { mode: 'pat', token: { expose: () => 'tok' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(DataCenterConfluenceApiClient).toHaveBeenCalledWith(config, mockAuth, mockLogger);
  });

  it('returns the created client instance', () => {
    const mockClient = {};
    vi.mocked(CloudConfluenceApiClient).mockImplementation(
      () => mockClient as unknown as CloudConfluenceApiClient,
    );
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    const result = factory.create(config);

    expect(result).toBe(mockClient);
  });
});
