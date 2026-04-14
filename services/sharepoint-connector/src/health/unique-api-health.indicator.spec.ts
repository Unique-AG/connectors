import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProxyService } from '../proxy/proxy.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { UniqueApiHealthIndicator } from './unique-api-health.indicator';

const TIMEOUT_MS = 3000;
const INGESTION_BASE_URL = 'https://ingestion.unique.app';
const SCOPE_MANAGEMENT_BASE_URL = 'https://scope.unique.app';

vi.mock('undici', () => ({
  fetch: vi.fn(),
}));

async function getUndiciFetch(): Promise<ReturnType<typeof vi.fn>> {
  const { fetch } = await import('undici');
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

describe('UniqueApiHealthIndicator', () => {
  let indicator: UniqueApiHealthIndicator;
  let mockFetch: ReturnType<typeof vi.fn>;
  const mockDispatcher = Symbol('dispatcher');

  beforeEach(async () => {
    vi.clearAllMocks();

    const { unit } = await TestBed.solitary(UniqueApiHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'health.connectivityTimeoutMs') {
            return TIMEOUT_MS;
          }
          if (key === 'unique') {
            return {
              ingestionServiceBaseUrl: INGESTION_BASE_URL,
              scopeManagementServiceBaseUrl: SCOPE_MANAGEMENT_BASE_URL,
              serviceAuthMode: 'external' as const,
            };
          }
          return undefined;
        }),
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher: vi.fn(() => mockDispatcher),
      }))
      .mock(UniqueAuthService)
      .impl((stub) => ({
        ...stub(),
        getToken: vi.fn().mockResolvedValue('test-token'),
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
    mockFetch = await getUndiciFetch();
  });

  it('returns up when both endpoints are reachable', async () => {
    mockFetch.mockResolvedValue(new Response('{"data":{"__typename":"Query"}}', { status: 200 }));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'up',
        ingestion: 'reachable',
        scopeManagement: 'reachable',
      },
    });
  });

  it('reports down when ingestion has a transport error and scope management is up', async () => {
    const connError = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    mockFetch
      .mockRejectedValueOnce(connError)
      .mockResolvedValueOnce(new Response('{"data":{"__typename":"Query"}}', { status: 200 }));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'unreachable',
        ingestionError: 'ECONNREFUSED',
        scopeManagement: 'reachable',
      },
    });
  });

  it('reports down when scope management is down and ingestion is up', async () => {
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    mockFetch
      .mockResolvedValueOnce(new Response('{"data":{"__typename":"Query"}}', { status: 200 }))
      .mockRejectedValueOnce(dnsError);

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'reachable',
        scopeManagement: 'unreachable',
        scopeManagementError: 'ENOTFOUND',
      },
    });
  });

  it('reports down with HTTP_401 when auth fails', async () => {
    mockFetch.mockResolvedValue(new Response('Unauthorized', { status: 401 }));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'unreachable',
        ingestionError: 'HTTP_401',
        scopeManagement: 'unreachable',
        scopeManagementError: 'HTTP_401',
      },
    });
  });

  it('reports down with HTTP_500 when server returns internal error', async () => {
    mockFetch.mockResolvedValue(new Response('Internal Server Error', { status: 500 }));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'unreachable',
        ingestionError: 'HTTP_500',
        scopeManagement: 'unreachable',
        scopeManagementError: 'HTTP_500',
      },
    });
  });

  it('reports down with HTTP_403 when access is forbidden', async () => {
    mockFetch
      .mockResolvedValueOnce(new Response('{"data":{"__typename":"Query"}}', { status: 200 }))
      .mockResolvedValueOnce(new Response('Forbidden', { status: 403 }));

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'reachable',
        scopeManagement: 'unreachable',
        scopeManagementError: 'HTTP_403',
      },
    });
  });

  it('reports down when both endpoints are down', async () => {
    const connError = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    mockFetch.mockRejectedValueOnce(connError).mockRejectedValueOnce(dnsError);

    const result = await indicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'unreachable',
        ingestionError: 'ECONNREFUSED',
        scopeManagement: 'unreachable',
        scopeManagementError: 'ENOTFOUND',
      },
    });
  });

  it('sends POST with __typename query, auth headers, and proxy dispatcher', async () => {
    mockFetch.mockResolvedValue(new Response('{"data":{"__typename":"Query"}}', { status: 200 }));

    await indicator.check('uniqueApi');

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(mockFetch).toHaveBeenCalledWith(`${INGESTION_BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer test-token' },
      body: JSON.stringify({ query: '{ __typename }' }),
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
    expect(mockFetch).toHaveBeenCalledWith(`${SCOPE_MANAGEMENT_BASE_URL}/graphql`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer test-token' },
      body: JSON.stringify({ query: '{ __typename }' }),
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
  });

  it('reports down with AUTH_FAILURE when getToken() rejects', async () => {
    const { unit: failingIndicator } = await TestBed.solitary(UniqueApiHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'health.connectivityTimeoutMs') {
            return TIMEOUT_MS;
          }
          if (key === 'unique') {
            return {
              ingestionServiceBaseUrl: INGESTION_BASE_URL,
              scopeManagementServiceBaseUrl: SCOPE_MANAGEMENT_BASE_URL,
              serviceAuthMode: 'external' as const,
            };
          }
          return undefined;
        }),
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher: vi.fn(() => mockDispatcher),
      }))
      .mock(UniqueAuthService)
      .impl((stub) => ({
        ...stub(),
        getToken: vi.fn().mockRejectedValue(new Error('Zitadel is down')),
      }))
      .mock(HealthIndicatorService)
      .impl(() => ({
        check: (key: string) => ({
          up: (data?: Record<string, unknown>) => ({ [key]: { status: 'up', ...data } }),
          down: (data?: Record<string, unknown>) => ({ [key]: { status: 'down', ...data } }),
        }),
      }))
      .compile();

    const result = await failingIndicator.check('uniqueApi');

    expect(result).toEqual({
      uniqueApi: {
        status: 'down',
        ingestion: 'unknown',
        scopeManagement: 'unknown',
        error: 'AUTH_FAILURE',
      },
    });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('uses cluster_local auth headers when serviceAuthMode is cluster_local', async () => {
    const extraHeaders = { 'x-custom': 'value' };
    const { unit: clusterIndicator } = await TestBed.solitary(UniqueApiHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'health.connectivityTimeoutMs') {
            return TIMEOUT_MS;
          }
          if (key === 'unique') {
            return {
              ingestionServiceBaseUrl: INGESTION_BASE_URL,
              scopeManagementServiceBaseUrl: SCOPE_MANAGEMENT_BASE_URL,
              serviceAuthMode: 'cluster_local' as const,
              serviceExtraHeaders: extraHeaders,
            };
          }
          return undefined;
        }),
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher: vi.fn(() => mockDispatcher),
      }))
      .mock(UniqueAuthService)
      .impl((stub) => ({
        ...stub(),
        getToken: vi.fn(),
      }))
      .mock(HealthIndicatorService)
      .impl(() => ({
        check: (key: string) => ({
          up: (data?: Record<string, unknown>) => ({ [key]: { status: 'up', ...data } }),
          down: (data?: Record<string, unknown>) => ({ [key]: { status: 'down', ...data } }),
        }),
      }))
      .compile();

    mockFetch.mockResolvedValue(new Response('{"data":{"__typename":"Query"}}', { status: 200 }));

    await clusterIndicator.check('uniqueApi');

    expect(mockFetch).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        headers: {
          'Content-Type': 'application/json',
          'x-service-id': 'sharepoint-connector',
          'x-custom': 'value',
        },
      }),
    );
  });
});
