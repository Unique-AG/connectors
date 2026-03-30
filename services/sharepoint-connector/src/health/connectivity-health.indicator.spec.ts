import { ConfigService } from '@nestjs/config';
import { HealthCheckError } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProxyService } from '../proxy/proxy.service';
import { ConnectivityHealthIndicator } from './connectivity-health.indicator';

const TIMEOUT_MS = 3000;
const BASE_URL = 'https://company.sharepoint.com';

vi.mock('undici', () => ({
  fetch: vi.fn(),
}));

async function getUndiciFetch(): Promise<ReturnType<typeof vi.fn>> {
  const { fetch } = await import('undici');
  return fetch as unknown as ReturnType<typeof vi.fn>;
}

describe('ConnectivityHealthIndicator', () => {
  let indicator: ConnectivityHealthIndicator;
  let mockFetch: ReturnType<typeof vi.fn>;
  const mockDispatcher = Symbol('dispatcher');

  beforeEach(async () => {
    vi.clearAllMocks();

    const { unit } = await TestBed.solitary(ConnectivityHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'health.connectivityTimeoutMs') return TIMEOUT_MS;
          if (key === 'sharepoint.baseUrl') return BASE_URL;
          return undefined;
        }),
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher: vi.fn(() => mockDispatcher),
      }))
      .compile();

    indicator = unit;
    mockFetch = await getUndiciFetch();
  });

  it('returns up when both Graph and SharePoint are reachable', async () => {
    mockFetch.mockResolvedValue(new Response());

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'up',
        graph: 'reachable',
        sharepoint: [{ tenant: 'default', status: 'reachable' }],
      },
    });
  });

  it('pings both endpoints with the proxy dispatcher and timeout signal', async () => {
    mockFetch.mockResolvedValue(new Response());

    await indicator.check('connectivity');

    expect(mockFetch).toHaveBeenCalledTimes(2);
    expect(mockFetch).toHaveBeenCalledWith('https://graph.microsoft.com/v1.0/', {
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
    expect(mockFetch).toHaveBeenCalledWith(`${BASE_URL}/`, {
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
  });

  it('reports down with graphError when Graph is unreachable', async () => {
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    mockFetch
      .mockRejectedValueOnce(dnsError)
      .mockResolvedValueOnce(new Response());

    try {
      await indicator.check('connectivity');
      expect.unreachable('expected HealthCheckError');
    } catch (error) {
      expect(error).toBeInstanceOf(HealthCheckError);
      expect((error as HealthCheckError).causes).toEqual({
        connectivity: {
          status: 'down',
          graph: 'unreachable',
          graphError: 'ENOTFOUND',
          sharepoint: [{ tenant: 'default', status: 'reachable' }],
        },
      });
    }
  });

  it('reports down with error in sharepoint array when SharePoint is unreachable', async () => {
    const timeoutError = Object.assign(new Error('connect ETIMEDOUT'), { code: 'ETIMEDOUT' });
    mockFetch
      .mockResolvedValueOnce(new Response())
      .mockRejectedValueOnce(timeoutError);

    try {
      await indicator.check('connectivity');
      expect.unreachable('expected HealthCheckError');
    } catch (error) {
      expect(error).toBeInstanceOf(HealthCheckError);
      expect((error as HealthCheckError).causes).toEqual({
        connectivity: {
          status: 'down',
          graph: 'reachable',
          sharepoint: [{ tenant: 'default', status: 'unreachable', error: 'ETIMEDOUT' }],
        },
      });
    }
  });

  it('reports down when both Graph and SharePoint are unreachable', async () => {
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    const connError = Object.assign(new Error('connect ECONNREFUSED'), { code: 'ECONNREFUSED' });
    mockFetch
      .mockRejectedValueOnce(dnsError)
      .mockRejectedValueOnce(connError);

    try {
      await indicator.check('connectivity');
      expect.unreachable('expected HealthCheckError');
    } catch (error) {
      expect(error).toBeInstanceOf(HealthCheckError);
      expect((error as HealthCheckError).causes).toEqual({
        connectivity: {
          status: 'down',
          graph: 'unreachable',
          graphError: 'ENOTFOUND',
          sharepoint: [{ tenant: 'default', status: 'unreachable', error: 'ECONNREFUSED' }],
        },
      });
    }
  });

  it('falls back to UNKNOWN when error has no code', async () => {
    mockFetch
      .mockRejectedValueOnce(new Error('unexpected'))
      .mockResolvedValueOnce(new Response());

    try {
      await indicator.check('connectivity');
      expect.unreachable('expected HealthCheckError');
    } catch (error) {
      expect(error).toBeInstanceOf(HealthCheckError);
      expect((error as HealthCheckError).causes).toEqual({
        connectivity: {
          status: 'down',
          graph: 'unreachable',
          graphError: 'UNKNOWN',
          sharepoint: [{ tenant: 'default', status: 'reachable' }],
        },
      });
    }
  });

  it('treats non-2xx HTTP responses as reachable', async () => {
    mockFetch
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 403 }));

    const result = await indicator.check('connectivity');

    expect(result).toEqual({
      connectivity: {
        status: 'up',
        graph: 'reachable',
        sharepoint: [{ tenant: 'default', status: 'reachable' }],
      },
    });
  });
});
