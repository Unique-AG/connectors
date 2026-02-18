import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceConfig } from '../config';
import { ServiceRegistry } from '../tenant/service-registry';
import { CloudApiAdapter } from './adapters/cloud-api.adapter';
import { DataCenterApiAdapter } from './adapters/data-center-api.adapter';
import { ConfluenceApiClient } from './confluence-api-client';
import { ConfluenceApiClientFactory } from './confluence-api-client.factory';

vi.mock('./confluence-api-client', () => ({
  ConfluenceApiClient: vi.fn(),
}));

const mockServiceRegistry = {
  getService: vi.fn(),
  getServiceLogger: vi.fn().mockReturnValue({ warn: vi.fn(), error: vi.fn() }),
} as unknown as ServiceRegistry;

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

describe('ConfluenceApiClientFactory', () => {
  it('creates a client with CloudApiAdapter for cloud config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(ConfluenceApiClient).toHaveBeenCalledWith(
      expect.any(CloudApiAdapter),
      config,
      mockServiceRegistry,
    );
  });

  it('creates a client with DataCenterApiAdapter for data-center config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'data-center',
      auth: { mode: 'pat', token: { expose: () => 'tok' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    expect(ConfluenceApiClient).toHaveBeenCalledWith(
      expect.any(DataCenterApiAdapter),
      config,
      mockServiceRegistry,
    );
  });

  it('passes baseUrl to the adapter', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry);
    const config = {
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: { expose: () => 's' } },
    } as unknown as ConfluenceConfig;

    factory.create(config);

    // biome-ignore lint/style/noNonNullAssertion: test assertion — call is guaranteed by the line above
    const adapterArg = vi.mocked(ConfluenceApiClient).mock.calls[0]![0] as CloudApiAdapter;
    expect(adapterArg.buildSearchUrl('test', 10, 0)).toContain('https://confluence.example.com');
  });
});
