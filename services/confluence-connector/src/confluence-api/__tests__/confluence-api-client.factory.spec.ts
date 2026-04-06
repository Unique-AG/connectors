import { createMock } from '@golevelup/ts-vitest';
import { describe, expect, it, vi } from 'vitest';
import type { ConfluenceAuth } from '../../auth/confluence-auth/confluence-auth.abstract';
import type { ConfluenceConfig } from '../../config';
import { createNoopMetrics } from '../../metrics/__mocks__/noop-metrics';
import type { ProxyService } from '../../proxy';
import { ServiceRegistry } from '../../tenant/service-registry';
import { RateLimitedHttpClient } from '../../utils/rate-limited-http-client';
import { Redacted } from '../../utils/redacted';
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

const mockAuth = createMock<ConfluenceAuth>();

const mockServiceRegistry = createMock<ServiceRegistry>({
  getService: vi.fn().mockReturnValue(mockAuth),
});

const mockProxyService = createMock<ProxyService>();

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

const noopMetrics = createNoopMetrics();

describe('ConfluenceApiClientFactory', () => {
  it('creates CloudConfluenceApiClient for cloud config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = createMock<ConfluenceConfig>({
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: new Redacted('s') },
    });

    factory.create(config, { attachmentsEnabled: false }, noopMetrics);

    expect(RateLimitedHttpClient).toHaveBeenCalledWith(100, noopMetrics, expect.anything());
    expect(CloudConfluenceApiClient).toHaveBeenCalledWith(
      config,
      mockAuth,
      expect.any(RateLimitedHttpClient),
      { attachmentsEnabled: false },
    );
  });

  it('creates DataCenterConfluenceApiClient for data-center config', () => {
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = createMock<ConfluenceConfig>({
      ...baseFields,
      instanceType: 'data-center',
      auth: { mode: 'pat', token: new Redacted('tok') },
    });

    factory.create(config, { attachmentsEnabled: false }, noopMetrics);

    expect(RateLimitedHttpClient).toHaveBeenCalledWith(100, noopMetrics, expect.anything());
    expect(DataCenterConfluenceApiClient).toHaveBeenCalledWith(
      config,
      mockAuth,
      expect.any(RateLimitedHttpClient),
      { attachmentsEnabled: false },
    );
  });

  it('returns the created client instance', () => {
    const mockClient = createMock<CloudConfluenceApiClient>();
    vi.mocked(CloudConfluenceApiClient).mockImplementation(() => mockClient);
    const factory = new ConfluenceApiClientFactory(mockServiceRegistry, mockProxyService);
    const config = createMock<ConfluenceConfig>({
      ...baseFields,
      instanceType: 'cloud',
      auth: { mode: 'oauth_2lo', clientId: 'id', clientSecret: new Redacted('s') },
    });

    const result = factory.create(config, { attachmentsEnabled: false }, noopMetrics);

    expect(result).toBe(mockClient);
  });
});
