import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KyckrConfig } from '~/config';
import type { Metrics } from './metrics';

vi.mock('undici', () => ({
  request: vi.fn(),
  Agent: class MockAgent {
    // biome-ignore lint/suspicious/noExplicitAny: mock class for constructor
    public constructor(_opts: any) {}
  },
}));

import { request } from 'undici';
import { KyckrApiError, KyckrHttpClient, KyckrRateLimitError } from './kyckr-http.client';

const mockRecorder: Pick<Metrics, 'recordApiRequest'> = {
  recordApiRequest: vi.fn(),
};

const stubConfig = { apiBaseUrl: 'https://api.example.com', apiKey: { value: 'key' } };
const mockedRequest = vi.mocked(request);

interface KyckrHttpClientInternals {
  normalizePath(path: string): string;
}

function mockResponse(
  statusCode: number,
  body: string,
  headers: Record<string, string> = {},
): Dispatcher.ResponseData {
  return {
    statusCode,
    headers,
    body: {
      async *[Symbol.asyncIterator]() {
        if (body.length > 0) {
          yield Buffer.from(body, 'utf-8');
        }
      },
      destroy: vi.fn(),
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('KyckrHttpClient', () => {
  let unit: KyckrHttpClient;
  let internals: KyckrHttpClientInternals;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new KyckrHttpClient(stubConfig as KyckrConfig, mockRecorder as unknown as Metrics);
    internals = unit as unknown as KyckrHttpClientInternals;
  });

  describe('get', () => {
    it('builds the request URL, forwards headers, and records metrics', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(200, JSON.stringify({ ok: true })));

      const result = await unit.get<{ ok: boolean }>('/companies', {
        name: 'Acme Ltd',
        isoCode: 'GB',
        unused: undefined,
      });

      expect(result).toEqual({ ok: true });
      expect(mockedRequest).toHaveBeenCalledWith(
        'https://api.example.com/companies?name=Acme+Ltd&isoCode=GB',
        {
          method: 'GET',
          headers: {
            Authorization: 'Bearer key',
            'Content-Type': 'application/json',
            Accept: 'application/json',
          },
          body: undefined,
          dispatcher: expect.any(Object),
        },
      );
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        method: 'GET',
        path: '/companies',
        status: 200,
        durationMs: expect.any(Number),
      });
    });

    it('returns undefined for empty successful responses', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(204, ''));

      const result = await unit.get('/orders');

      expect(result).toBeUndefined();
    });

    it('throws KyckrApiError with detail and correlationId from the response envelope', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockResponse(
          404,
          JSON.stringify({
            correlationId: 'corr-404',
            data: { detail: 'Order not found' },
          }),
        ),
      );

      await expect(unit.get('/orders/ORD-1')).rejects.toMatchObject({
        name: 'KyckrApiError',
        status: 404,
        path: '/orders/ORD-1',
        message: 'Order not found',
        correlationId: 'corr-404',
      } satisfies Partial<KyckrApiError>);
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        method: 'GET',
        path: '/orders/:orderId',
        status: 404,
        durationMs: expect.any(Number),
      });
    });

    it('throws KyckrRateLimitError with retryAfterSeconds from the Retry-After header', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(429, '', { 'retry-after': '60' }));

      await expect(unit.get('/companies')).rejects.toMatchObject({
        name: 'KyckrRateLimitError',
        status: 429,
        path: '/companies',
        retryAfterSeconds: 60,
        message: 'Rate limit exceeded. Retry after 60s.',
      } satisfies Partial<KyckrRateLimitError>);
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        method: 'GET',
        path: '/companies',
        status: 429,
        durationMs: expect.any(Number),
      });
    });

    it('throws KyckrRateLimitError with undefined retryAfterSeconds when Retry-After is absent', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(429, ''));

      await expect(unit.get('/orders')).rejects.toMatchObject({
        name: 'KyckrRateLimitError',
        status: 429,
        retryAfterSeconds: undefined,
        message: 'Rate limit exceeded.',
      } satisfies Partial<KyckrRateLimitError>);
    });

    it('throws when the response body exceeds the 10 MiB size cap', async () => {
      const oversized = 'x'.repeat(11 * 1024 * 1024);
      mockedRequest.mockResolvedValueOnce(mockResponse(200, oversized));

      await expect(unit.get('/companies')).rejects.toThrow(/exceeded/);
    });

    it('rethrows transport errors after logging and still records metrics', async () => {
      const error = new Error('ECONNRESET');
      mockedRequest.mockRejectedValueOnce(error);

      await expect(unit.get('/companies')).rejects.toThrow('ECONNRESET');
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        method: 'GET',
        path: '/companies',
        status: 0,
        durationMs: expect.any(Number),
      });
    });
  });

  describe('post', () => {
    it('serializes the request body as JSON', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockResponse(200, JSON.stringify({ data: { orderId: 'ORD-1' } })),
      );

      const result = await unit.post<{ data: { orderId: string } }>('/orders', {
        kyckrId: 'GB|123',
        productId: 'DOC-1',
      });

      expect(result).toEqual({ data: { orderId: 'ORD-1' } });
      expect(mockedRequest).toHaveBeenCalledWith(
        'https://api.example.com/orders',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({
            kyckrId: 'GB|123',
            productId: 'DOC-1',
          }),
          dispatcher: expect.any(Object),
        }),
      );
    });
  });

  describe('normalizePath', () => {
    it('preserves /companies', () => {
      expect(internals.normalizePath('/companies')).toBe('/companies');
    });

    it('preserves /orders', () => {
      expect(internals.normalizePath('/orders')).toBe('/orders');
    });

    it('replaces a URL-encoded kyckrId in /companies/:kyckrId/lite', () => {
      expect(internals.normalizePath('/companies/GB%7CMTE2NTUyOTA/lite')).toBe(
        '/companies/:kyckrId/lite',
      );
    });

    it('replaces a URL-encoded kyckrId in /companies/:kyckrId/enhanced', () => {
      expect(internals.normalizePath('/companies/GB%7CMTE2NTUyOTA/enhanced')).toBe(
        '/companies/:kyckrId/enhanced',
      );
    });

    it('replaces a URL-encoded kyckrId in /companies/:kyckrId/documents', () => {
      expect(internals.normalizePath('/companies/GB%7CMTE2NTUyOTA/documents')).toBe(
        '/companies/:kyckrId/documents',
      );
    });

    it('replaces a plain kyckrId in /companies/:kyckrId/lite', () => {
      expect(internals.normalizePath('/companies/some-plain-id/lite')).toBe(
        '/companies/:kyckrId/lite',
      );
    });

    it('replaces an orderId in /orders/:orderId', () => {
      expect(internals.normalizePath('/orders/abc-123-def')).toBe('/orders/:orderId');
    });

    it('replaces an orderId in /orders/:orderId/download', () => {
      expect(internals.normalizePath('/orders/abc-123-def/download')).toBe(
        '/orders/:orderId/download',
      );
    });

    it('collapses unknown routes to [unknown] to bound metric cardinality', () => {
      expect(internals.normalizePath('/unknown/route')).toBe('[unknown]');
    });
  });
});
