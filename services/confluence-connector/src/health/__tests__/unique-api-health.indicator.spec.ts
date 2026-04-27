import { UniqueApiClient } from '@unique-ag/unique-api';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProxyService } from '../../proxy/proxy.service';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { UniqueApiHealthIndicator } from '../unique-api-health.indicator';

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

interface TenantSetup {
  name: string;
  authMode: 'cluster_local' | 'external';
  ingestionUrl?: string;
  scopeManagementUrl?: string;
  serviceExtraHeaders?: Record<string, string>;
  tokenProvider?: () => Promise<string>;
  status?: 'active' | 'deleted';
}

function makeTenant(setup: TenantSetup): TenantContext {
  const ingestionUrl = setup.ingestionUrl ?? 'http://ingestion.local:8091';
  const scopeManagementUrl = setup.scopeManagementUrl ?? 'http://scope-management.local:8094';
  const uniqueConfig =
    setup.authMode === 'cluster_local'
      ? {
          serviceAuthMode: 'cluster_local' as const,
          ingestionServiceBaseUrl: ingestionUrl,
          scopeManagementServiceBaseUrl: scopeManagementUrl,
          serviceExtraHeaders: setup.serviceExtraHeaders ?? {
            'x-company-id': 'company-1',
            'x-user-id': 'user-1',
          },
        }
      : {
          serviceAuthMode: 'external' as const,
          ingestionServiceBaseUrl: ingestionUrl,
          scopeManagementServiceBaseUrl: scopeManagementUrl,
        };
  return {
    name: setup.name,
    status: setup.status ?? 'active',
    isScanning: false,
    config: { unique: uniqueConfig },
  } as unknown as TenantContext;
}

describe('UniqueApiHealthIndicator', () => {
  let indicator: UniqueApiHealthIndicator;
  let mockFetch: ReturnType<typeof vi.fn>;
  let tenants: TenantContext[];
  let serviceRegistry: ServiceRegistry;
  const mockDispatcher = Symbol('dispatcher');
  const proxyMode = vi.fn();

  async function buildIndicator(): Promise<void> {
    serviceRegistry = new ServiceRegistry();

    const { unit } = await TestBed.solitary(UniqueApiHealthIndicator)
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
        getDispatcher: vi.fn((opts: { mode: 'always' | 'never' }) => {
          proxyMode(opts.mode);
          return mockDispatcher;
        }),
      }))
      .mock(TenantRegistry)
      .impl((stub) => ({
        ...stub(),
        getAllTenants: vi.fn(() => tenants),
        run: vi.fn(<R>(tenant: TenantContext, fn: () => R): R => tenantStorage.run(tenant, fn)),
      }))
      .mock(ServiceRegistry)
      .final(serviceRegistry)
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

  function registerExternalClient(tenantName: string, getToken: () => Promise<string>): void {
    const client = { auth: { getToken } } as unknown as UniqueApiClient;
    serviceRegistry.register(tenantName, UniqueApiClient, client);
  }

  beforeEach(async () => {
    vi.clearAllMocks();
    tenants = [];
    mockFetch = await getUndiciFetch();
  });

  it('reports up with cluster_local headers when both endpoints are reachable', async () => {
    tenants = [
      makeTenant({
        name: 'tenant-a',
        authMode: 'cluster_local',
        serviceExtraHeaders: { 'x-company-id': 'company-1', 'x-user-id': 'user-1' },
      }),
    ];
    await buildIndicator();
    mockFetch.mockResolvedValue(new Response('{}'));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'up',
        ingestion: [{ tenant: 'tenant-a', status: 'reachable' }],
        scopeManagement: [{ tenant: 'tenant-a', status: 'reachable' }],
      },
    });
    expect(mockFetch).toHaveBeenCalledWith(
      'http://ingestion.local:8091/graphql',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ query: '{ __typename }' }),
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
          'x-service-id': 'confluence-connector',
          'x-company-id': 'company-1',
          'x-user-id': 'user-1',
        }),
      }),
    );
    // cluster_local must bypass the proxy.
    expect(proxyMode).toHaveBeenCalledWith('never');
  });

  it('uses the bearer token returned by the per-tenant UniqueApiClient for external auth', async () => {
    tenants = [makeTenant({ name: 'ext-tenant', authMode: 'external' })];
    await buildIndicator();
    registerExternalClient('ext-tenant', () => Promise.resolve('zitadel-token'));
    mockFetch.mockResolvedValue(new Response('{}'));

    await indicator.check('uniqueApi');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://ingestion.local:8091/graphql',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer zitadel-token' }),
      }),
    );
    // external mode must route through the proxy.
    expect(proxyMode).toHaveBeenCalledWith('always');
  });

  it('reports AUTH_FAILURE when token acquisition throws', async () => {
    tenants = [makeTenant({ name: 'ext-tenant', authMode: 'external' })];
    await buildIndicator();
    registerExternalClient('ext-tenant', () => Promise.reject(new Error('zitadel down')));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: [{ tenant: 'ext-tenant', status: 'unreachable', error: 'AUTH_FAILURE' }],
        scopeManagement: [{ tenant: 'ext-tenant', status: 'unreachable', error: 'AUTH_FAILURE' }],
      },
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('flags non-2xx responses with HTTP_<status>', async () => {
    tenants = [makeTenant({ name: 'tenant-a', authMode: 'cluster_local' })];
    await buildIndicator();
    mockFetch
      .mockResolvedValueOnce(new Response('{}', { status: 503 }))
      .mockResolvedValueOnce(new Response('{}'));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: [{ tenant: 'tenant-a', status: 'unreachable', error: 'HTTP_503' }],
        scopeManagement: [{ tenant: 'tenant-a', status: 'reachable' }],
      },
    });
  });

  it('returns transport-level error codes when fetch rejects', async () => {
    tenants = [makeTenant({ name: 'tenant-a', authMode: 'cluster_local' })];
    await buildIndicator();
    const refused = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    mockFetch.mockRejectedValue(refused);

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: [{ tenant: 'tenant-a', status: 'unreachable', error: 'ECONNREFUSED' }],
        scopeManagement: [{ tenant: 'tenant-a', status: 'unreachable', error: 'ECONNREFUSED' }],
      },
    });
  });
});
