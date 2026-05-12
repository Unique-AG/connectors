import type { MetricService } from 'nestjs-otel';
import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KyckrConfig } from '~/config';

vi.mock('undici', () => ({
  request: vi.fn(),
}));

import { request } from 'undici';
import { KyckrApiError, KyckrHttpClient } from './kyckr-http.client';

const mockCounter = { add: vi.fn() };
const mockHistogram = { record: vi.fn() };
const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn().mockReturnValue(mockCounter),
  getHistogram: vi.fn().mockReturnValue(mockHistogram),
};

const stubConfig = { apiBaseUrl: 'https://api.example.com', apiKey: { value: 'key' } };
const mockedRequest = vi.mocked(request);

interface KyckrHttpClientInternals {
  normalizePath(path: string): string;
}

function mockResponse(statusCode: number, body: string): Dispatcher.ResponseData {
  return {
    statusCode,
    headers: {},
    body: {
      text: vi.fn().mockResolvedValue(body),
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('KyckrHttpClient', () => {
  let unit: KyckrHttpClient;
  let internals: KyckrHttpClientInternals;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new KyckrHttpClient(stubConfig as KyckrConfig, mockMetricService as MetricService);
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
        },
      );
      expect(mockCounter.add).toHaveBeenCalledWith(1, {
        method: 'GET',
        path: '/companies',
        status: '200',
      });
      expect(mockHistogram.record).toHaveBeenCalledWith(expect.any(Number), {
        method: 'GET',
        path: '/companies',
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
      expect(mockCounter.add).toHaveBeenCalledWith(1, {
        method: 'GET',
        path: '/orders/:orderId',
        status: '404',
      });
    });

    it('rethrows transport errors after logging and still records metrics', async () => {
      const error = new Error('ECONNRESET');
      mockedRequest.mockRejectedValueOnce(error);

      await expect(unit.get('/companies')).rejects.toThrow('ECONNRESET');
      expect(mockCounter.add).toHaveBeenCalledWith(1, {
        method: 'GET',
        path: '/companies',
        status: '0',
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

    it('collapses unknown routes to [unknown] to bound metric cardinality', () => {
      expect(internals.normalizePath('/unknown/route')).toBe('[unknown]');
    });
  });
});
