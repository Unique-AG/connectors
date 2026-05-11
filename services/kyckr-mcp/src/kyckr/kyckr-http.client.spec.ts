import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KyckrConfig } from '~/config';
import { KyckrHttpClient } from './kyckr-http.client';

const mockCounter = { add: vi.fn() };
const mockHistogram = { record: vi.fn() };
const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn().mockReturnValue(mockCounter),
  getHistogram: vi.fn().mockReturnValue(mockHistogram),
};

const stubConfig = { apiBaseUrl: 'https://api.example.com', apiKey: { value: 'key' } };

interface KyckrHttpClientInternals {
  normalizePath(path: string): string;
}

describe('KyckrHttpClient', () => {
  let unit: KyckrHttpClient;
  let internals: KyckrHttpClientInternals;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new KyckrHttpClient(stubConfig as KyckrConfig, mockMetricService as MetricService);
    internals = unit as unknown as KyckrHttpClientInternals;
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

    it('returns path unchanged for unknown routes', () => {
      expect(internals.normalizePath('/unknown/route')).toBe('/unknown/route');
    });
  });
});
