import { describe, expect, it } from 'vitest';
import { UniqueAuth } from '../unique-auth';
import { ClusterLocalAuthStrategy } from './cluster-local-auth.strategy';

function createConfig() {
  return {
    serviceAuthMode: 'cluster_local' as const,
    serviceExtraHeaders: {
      'x-company-id': 'company-123',
      'x-user-id': 'user-456',
    },
    ingestionServiceBaseUrl: 'https://ingestion.example.com',
    scopeManagementServiceBaseUrl: 'https://scope.example.com',
    apiRateLimitPerMinute: 100,
  };
}

describe('ClusterLocalAuthStrategy', () => {
  it('extends UniqueServiceAuth', () => {
    const strategy = new ClusterLocalAuthStrategy(createConfig());

    expect(strategy).toBeInstanceOf(UniqueAuth);
  });

  it('returns x-service-id header with confluence-connector value', async () => {
    const strategy = new ClusterLocalAuthStrategy(createConfig());

    const headers = await strategy.getHeaders();

    expect(headers['x-service-id']).toBe('confluence-connector');
  });

  it('returns service extra headers from config', async () => {
    const strategy = new ClusterLocalAuthStrategy(createConfig());

    const headers = await strategy.getHeaders();

    expect(headers['x-company-id']).toBe('company-123');
    expect(headers['x-user-id']).toBe('user-456');
  });

  it('returns all expected headers combined', async () => {
    const strategy = new ClusterLocalAuthStrategy(createConfig());

    const headers = await strategy.getHeaders();

    expect(headers).toEqual({
      'x-service-id': 'confluence-connector',
      'x-company-id': 'company-123',
      'x-user-id': 'user-456',
    });
  });

  it('returns the same headers on every call', async () => {
    const strategy = new ClusterLocalAuthStrategy(createConfig());

    const first = await strategy.getHeaders();
    const second = await strategy.getHeaders();

    expect(first).toEqual(second);
  });

  it('preserves additional custom headers from config', async () => {
    const config = {
      ...createConfig(),
      serviceExtraHeaders: {
        'x-company-id': 'company-123',
        'x-user-id': 'user-456',
        'x-custom': 'custom-value',
      },
    };

    const strategy = new ClusterLocalAuthStrategy(config);
    const headers = await strategy.getHeaders();

    expect(headers['x-custom']).toBe('custom-value');
  });

  it('prevents serviceExtraHeaders from overwriting x-service-id', async () => {
    const config = {
      ...createConfig(),
      serviceExtraHeaders: {
        'x-company-id': 'company-123',
        'x-user-id': 'user-456',
        'x-service-id': 'malicious-override',
      },
    };

    const strategy = new ClusterLocalAuthStrategy(config);
    const headers = await strategy.getHeaders();

    expect(headers['x-service-id']).toBe('confluence-connector');
  });
});
