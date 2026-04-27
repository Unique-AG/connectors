import { UniqueApiClient } from '@unique-ag/unique-api';
import { createMock } from '@golevelup/ts-vitest';
import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { Response as UndiciResponse } from 'undici';
import { beforeEach, describe, expect, it, type MockedFunction, vi } from 'vitest';
import { type TenantConfig, TenantStatus, UniqueAuthMode } from '../../config';
import { AuthMode } from '../../config/confluence.schema';
import { ProxyService } from '../../proxy/proxy.service';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { TenantRegistry } from '../../tenant/tenant-registry';
import { Redacted } from '../../utils/redacted';
import { UniqueApiHealthIndicator } from '../unique-api-health.indicator';

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

interface TenantSetup {
  name: string;
  authMode: 'cluster_local' | 'external';
  ingestionUrl?: string;
  scopeManagementUrl?: string;
  serviceExtraHeaders?: Record<string, string>;
  tokenProvider?: () => Promise<string>;
  status?: 'active' | 'deleted';
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
    attachments: { enabled: true, allowedExtensions: ['pdf'], maxFileSizeMb: 200 },
  },
} satisfies TenantConfig;

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
          zitadelOauthTokenUrl: 'https://idp.example.com/oauth/v2/token',
          zitadelProjectId: new Redacted('project-id'),
          zitadelClientId: 'client-id',
          zitadelClientSecret: new Redacted('client-secret'),
          apiRateLimitPerMinute: 100,
        };
  return {
    name: setup.name,
    status: setup.status ?? TenantStatus.Active,
    isScanning: false,
    config: {
      ...baseTenantConfig,
      unique: {
        ...uniqueConfig,
        apiRateLimitPerMinute: 100,
      },
    },
  } satisfies TenantContext;
}

describe('UniqueApiHealthIndicator', () => {
  let indicator: UniqueApiHealthIndicator;
  let mockFetch: MockedFunction<UndiciFetch>;
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
    const client = createMock<UniqueApiClient>({ auth: { getToken } });
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
    mockFetch.mockResolvedValue(new UndiciResponse('{}'));

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
    mockFetch.mockResolvedValue(new UndiciResponse('{}'));

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
      .mockResolvedValueOnce(new UndiciResponse('{}', { status: 503 }))
      .mockResolvedValueOnce(new UndiciResponse('{}'));

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
