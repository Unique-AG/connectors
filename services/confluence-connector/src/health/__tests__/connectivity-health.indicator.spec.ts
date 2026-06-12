import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { Response as UndiciResponse } from 'undici';
import { beforeEach, describe, expect, it, type MockedFunction, vi } from 'vitest';
import { type TenantConfig, TenantStatus, UniqueAuthMode } from '../../config';
import { AuthMode } from '../../config/confluence.schema';
import { ProxyService } from '../../proxy/proxy.service';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { Redacted } from '../../utils/redacted';
import { ConnectivityHealthIndicator } from '../connectivity-health.indicator';

const TIMEOUT_MS = 3000;
type UndiciFetch = typeof import('undici').fetch;

vi.mock('undici', async (importOriginal) => {
  const actual = await importOriginal<typeof import('undici')>();
  return {
    ...actual,
    fetch: vi.fn(),
  };
});

async function getUndiciFetch(): Promise<MockedFunction<UndiciFetch>> {
  const { fetch } = await import('undici');
  return vi.mocked(fetch);
}

const baseTenantConfig = {
  confluence: {
    instanceType: 'cloud',
    baseUrl: 'https://tenant.atlassian.net',
    cloudId: 'cloud-id',
    apiRateLimitPerMinute: 100,
    ingestSingleLabel: 'ai-ingest',
    ingestAllLabel: 'ai-ingest-all',
    auth: {
      mode: AuthMode.OAuth2Lo,
      clientId: 'client-id',
      clientSecret: new Redacted('client-secret'),
    },
  },
  unique: {
    serviceAuthMode: UniqueAuthMode.ClusterLocal,
    serviceExtraHeaders: { 'x-company-id': 'company-id', 'x-user-id': 'user-id' },
    ingestionServiceBaseUrl: 'http://ingestion.local:8091',
    scopeManagementServiceBaseUrl: 'http://scope-management.local:8094',
    apiRateLimitPerMinute: 100,
  },
  processing: { scanIntervalCron: '*/5 * * * *', concurrency: 1 },
  ingestion: {
    ingestionMode: 'flat',
    scopeId: 'scope-id',
    storeInternally: true,
    useV1KeyFormat: false,
    attachments: {
      enabled: true,
      allowedMimeTypes: ['application/pdf'],
      imageOcrEnabled: false,
      inlineImagesEnabled: true,
      maxFileSizeMb: 200,
    },
  },
} satisfies TenantConfig;

function makeCloudTenant(
  name: string,
  baseUrl = `https://${name}.atlassian.net`,
  status: TenantContext['status'] = TenantStatus.Active,
): TenantContext {
  return {
    name,
    status,
    isScanning: false,
    config: {
      ...baseTenantConfig,
      confluence: { ...baseTenantConfig.confluence, baseUrl },
    },
  } satisfies TenantContext;
}

function makeDataCenterTenant(name: string, baseUrl: string): TenantContext {
  return {
    name,
    status: TenantStatus.Active,
    isScanning: false,
    config: {
      ...baseTenantConfig,
      confluence: {
        instanceType: 'data-center',
        baseUrl,
        apiRateLimitPerMinute: 100,
        ingestSingleLabel: 'ai-ingest',
        ingestAllLabel: 'ai-ingest-all',
        auth: { mode: AuthMode.Pat, token: new Redacted('pat-token') },
      },
    },
  } satisfies TenantContext;
}

function makeDeletedTenant(name: string, baseUrl: string): TenantContext {
  return makeCloudTenant(name, baseUrl, TenantStatus.Deleted);
}

describe('ConnectivityHealthIndicator', () => {
  let indicator: ConnectivityHealthIndicator;
  let mockFetch: MockedFunction<UndiciFetch>;
  let tenants: TenantContext[];
  const mockDispatcher = Symbol('dispatcher');

  async function buildIndicator(): Promise<void> {
    const { unit } = await TestBed.solitary(ConnectivityHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'health.connectivityTimeoutMs') {
            return TIMEOUT_MS;
          }
          return undefined;
        }),
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher: vi.fn(() => mockDispatcher),
      }))
      .mock(TenantRegistry)
      .impl((stub) => ({
        ...stub(),
        getAllTenants: vi.fn(() => tenants),
      }))
      .mock(HealthIndicatorService)
      .impl(() => ({
        check: (key: string) => ({
          up: (data?: Record<string, unknown>) => ({ [key]: { status: 'up', ...data } }),
          down: (data?: Record<string, unknown>) => ({ [key]: { status: 'down', ...data } }),
        }),
      }))
      .compile();
    indicator = unit;
  }

  beforeEach(async () => {
    vi.clearAllMocks();
    tenants = [];
    mockFetch = await getUndiciFetch();
  });

  it('returns up when atlassian and tenant base URLs are reachable', async () => {
    tenants = [makeCloudTenant('tenant-a', 'https://acme.atlassian.net')];
    await buildIndicator();
    mockFetch.mockResolvedValue(new UndiciResponse());

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'up',
        atlassian: 'reachable',
        confluence: [{ tenant: 'tenant-a', status: 'reachable' }],
      },
    });
  });

  it('omits the atlassian check when no cloud tenants exist', async () => {
    tenants = [makeDataCenterTenant('dc-tenant', 'https://confluence.acme.com')];
    await buildIndicator();
    mockFetch.mockResolvedValue(new UndiciResponse());

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'up',
        confluence: [{ tenant: 'dc-tenant', status: 'reachable' }],
      },
    });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith('https://confluence.acme.com/', {
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
  });

  it('deduplicates pings when several tenants share a base URL', async () => {
    tenants = [
      makeCloudTenant('tenant-a', 'https://acme.atlassian.net'),
      makeCloudTenant('tenant-b', 'https://acme.atlassian.net'),
    ];
    await buildIndicator();
    mockFetch.mockResolvedValue(new UndiciResponse());

    const result = await indicator.check('connectivity');

    // Both tenants land in the result, but the shared base URL is only pinged once.
    expect(result).toEqual({
      connectivity: {
        status: 'up',
        atlassian: 'reachable',
        confluence: [
          { tenant: 'tenant-a', status: 'reachable' },
          { tenant: 'tenant-b', status: 'reachable' },
        ],
      },
    });
    // 1 atlassian ping + 1 deduped confluence ping.
    expect(mockFetch).toHaveBeenCalledTimes(2);
  });

  it('skips deleted tenants because they no longer talk to Confluence', async () => {
    tenants = [
      makeCloudTenant('active', 'https://active.atlassian.net'),
      makeDeletedTenant('gone', 'https://gone.atlassian.net'),
    ];
    await buildIndicator();
    mockFetch.mockResolvedValue(new UndiciResponse());

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'up',
        atlassian: 'reachable',
        confluence: [{ tenant: 'active', status: 'reachable' }],
      },
    });
  });

  it('reports down with atlassianError when the atlassian API is unreachable', async () => {
    tenants = [makeCloudTenant('tenant-a', 'https://acme.atlassian.net')];
    await buildIndicator();
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    mockFetch.mockRejectedValueOnce(dnsError).mockResolvedValueOnce(new UndiciResponse());

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'down',
        atlassian: 'unreachable',
        atlassianError: 'ENOTFOUND',
        confluence: [{ tenant: 'tenant-a', status: 'reachable' }],
      },
    });
  });

  it('reports down with per-tenant error when one Confluence base URL is unreachable', async () => {
    tenants = [
      makeCloudTenant('healthy', 'https://healthy.atlassian.net'),
      makeCloudTenant('broken', 'https://broken.atlassian.net'),
    ];
    await buildIndicator();
    const timeoutError = Object.assign(new Error('connect ETIMEDOUT'), { code: 'ETIMEDOUT' });
    mockFetch
      // atlassian ping
      .mockResolvedValueOnce(new UndiciResponse())
      // healthy ping
      .mockResolvedValueOnce(new UndiciResponse())
      // broken ping
      .mockRejectedValueOnce(timeoutError);

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'down',
        atlassian: 'reachable',
        confluence: [
          { tenant: 'healthy', status: 'reachable' },
          { tenant: 'broken', status: 'unreachable', error: 'ETIMEDOUT' },
        ],
      },
    });
  });
});
