import { ProxyService } from '@unique-ag/proxy';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestionConfig, ingestionConfig } from '~/config';
import { MsGraphConnectivityHealthIndicator } from './ms-graph-connectivity-health.indicator';

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

describe('MsGraphConnectivityHealthIndicator', () => {
  let indicator: MsGraphConnectivityHealthIndicator;
  let mockFetch: ReturnType<typeof vi.fn>;
  let getDispatcher: ReturnType<typeof vi.fn>;
  const mockDispatcher = Symbol('dispatcher');

  beforeEach(async () => {
    vi.clearAllMocks();
    getDispatcher = vi.fn(() => mockDispatcher);

    const { unit } = await TestBed.solitary(MsGraphConnectivityHealthIndicator)
      .mock<IngestionConfig>(ingestionConfig.KEY)
      .impl(() => ({
        connectivityTimeoutMs: TIMEOUT_MS,
      }))
      .mock(ProxyService)
      .impl((stub) => ({
        ...stub(),
        getDispatcher,
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

  it('returns up when Graph is reachable', async () => {
    mockFetch.mockResolvedValue(new Response());

    const result = await indicator.check('msGraphConnectivity');

    expect(result).toEqual({
      msGraphConnectivity: {
        status: 'up',
        graph: 'reachable',
      },
    });
  });

  it('pings Graph with the always-mode proxy dispatcher and timeout signal', async () => {
    mockFetch.mockResolvedValue(new Response());

    await indicator.check('msGraphConnectivity');

    expect(getDispatcher).toHaveBeenCalledWith({ mode: 'always' });
    expect(mockFetch).toHaveBeenCalledTimes(1);
    expect(mockFetch).toHaveBeenCalledWith('https://graph.microsoft.com/v1.0/', {
      dispatcher: mockDispatcher,
      signal: expect.any(AbortSignal),
    });
  });

  it('reports down with graphError when Graph is unreachable', async () => {
    const dnsError = Object.assign(new Error('getaddrinfo ENOTFOUND'), { code: 'ENOTFOUND' });
    mockFetch.mockRejectedValue(dnsError);

    const result = await indicator.check('msGraphConnectivity');

    expect(result).toEqual({
      msGraphConnectivity: {
        status: 'down',
        graph: 'unreachable',
        graphError: 'ENOTFOUND',
      },
    });
  });

  it('treats non-2xx HTTP responses as reachable', async () => {
    mockFetch.mockResolvedValue(new Response(null, { status: 401 }));

    const result = await indicator.check('msGraphConnectivity');

    expect(result).toEqual({
      msGraphConnectivity: {
        status: 'up',
        graph: 'reachable',
      },
    });
  });
});
