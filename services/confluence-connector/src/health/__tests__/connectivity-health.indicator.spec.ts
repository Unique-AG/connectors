import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProxyService } from '../../proxy/proxy.service';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { ConnectivityHealthIndicator } from '../connectivity-health.indicator';

const TIMEOUT_MS = 3000;

vi.mock('undici', async (importOriginal) => {
  const actual = await importOriginal<typeof import('undici')>();
  return {
    ...actual,
    fetch: vi.fn(),
  };
});

async function getUndiciFetch(): Promise<ReturnType<typeof vi.fn>> {
  const { fetch } = await import('undici');
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

function makeCloudTenant(name: string, baseUrl = `https://${name}.atlassian.net`): TenantContext {
  return {
    name,
    status: 'active',
    isScanning: false,
    config: {
      confluence: {
        instanceType: 'cloud',
        baseUrl,
      },
    },
  } as unknown as TenantContext;
}

function makeDataCenterTenant(name: string, baseUrl: string): TenantContext {
  return {
    name,
    status: 'active',
    isScanning: false,
    config: {
      confluence: {
        instanceType: 'data-center',
        baseUrl,
      },
    },
  } as unknown as TenantContext;
}

function makeDeletedTenant(name: string, baseUrl: string): TenantContext {
  return {
    name,
    status: 'deleted',
    isScanning: false,
    config: {
      confluence: { instanceType: 'cloud', baseUrl },
    },
  } as unknown as TenantContext;
}

describe('ConnectivityHealthIndicator', () => {
  let indicator: ConnectivityHealthIndicator;
  let mockFetch: ReturnType<typeof vi.fn>;
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
    mockFetch.mockResolvedValue(new Response());

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
    mockFetch.mockResolvedValue(new Response());

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
    mockFetch.mockResolvedValue(new Response());

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
    mockFetch.mockResolvedValue(new Response());

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
    mockFetch.mockRejectedValueOnce(dnsError).mockResolvedValueOnce(new Response());

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
      .mockResolvedValueOnce(new Response())
      // healthy ping
      .mockResolvedValueOnce(new Response())
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
