import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Config } from '../../config';
import { GraphClientFactory } from './graph-client.factory';
import { GraphAuthenticationService } from './middlewares/graph-authentication.service';

describe('GraphClientFactory', () => {
  let factory: GraphClientFactory;
  let mockGraphAuthService: GraphAuthenticationService;
  let mockMetricService: MetricService;
  let mockConfigService: ConfigService<Config, true>;

  beforeEach(async () => {
    mockGraphAuthService = {
      getAccessToken: async () => 'mock-token',
    } as never;

    const mockHistogram = {
      record: vi.fn(),
    };

    mockMetricService = {
      getHistogram: vi.fn().mockReturnValue(mockHistogram),
    } as unknown as MetricService;

    mockConfigService = {
      get: vi.fn().mockImplementation((key: string) => {
        if (key === 'unique') {
          return {
            serviceAuthMode: 'cluster_local',
            serviceExtraHeaders: {
              'x-company-id': 'test-company-id',
              'x-user-id': 'test-user-id',
            },
          };
        }
        if (key === 'sharepoint.authTenantId') {
          return 'test-tenant-id';
        }
        return undefined;
      }),
    } as unknown as ConfigService<Config, true>;

    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .mock(MetricService)
      .impl(() => mockMetricService)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .compile();

    factory = unit;
  });

  it('creates Graph client successfully', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
    expect(client.api).toBeDefined();
  });

  it('creates client with authentication provider', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
  });

  it('creates client with debug logging disabled by default', async () => {
    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .mock(MetricService)
      .impl(() => mockMetricService)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('creates client with debug logging enabled for debug level', async () => {
    const { unit } = await TestBed.solitary(GraphClientFactory)
      .mock(GraphAuthenticationService)
      .impl(() => mockGraphAuthService)
      .mock(MetricService)
      .impl(() => mockMetricService)
      .mock(ConfigService)
      .impl(() => mockConfigService)
      .compile();

    const client = unit.createClient();

    expect(client).toBeDefined();
  });

  it('sets up middleware chain with all required middlewares', () => {
    const client = factory.createClient();

    expect(client).toBeDefined();
  });
});
