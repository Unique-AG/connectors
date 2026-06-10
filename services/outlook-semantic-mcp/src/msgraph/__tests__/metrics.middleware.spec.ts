import type { MetricService } from 'nestjs-otel';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MetricsMiddleware } from '../metrics.middleware';

const mockCounter = { add: vi.fn() };
const mockHistogram = { record: vi.fn() };
const mockMetricService: Pick<MetricService, 'getCounter' | 'getHistogram'> = {
  getCounter: vi.fn().mockReturnValue(mockCounter),
  getHistogram: vi.fn().mockReturnValue(mockHistogram),
};

interface MetricsMiddlewareInternals {
  extractEndpoint(request: RequestInfo): string;
  sanitizeEndpointForMetrics(endpoint: string): string;
}

describe('MetricsMiddleware', () => {
  let unit: MetricsMiddleware;
  let internals: MetricsMiddlewareInternals;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new MetricsMiddleware(mockMetricService as MetricService);
    internals = unit as unknown as MetricsMiddlewareInternals;
  });

  describe('extractEndpoint', () => {
    it('strips v1.0 version prefix from path', () => {
      expect(internals.extractEndpoint('https://graph.microsoft.com/v1.0/me/messages')).toBe(
        '/me/messages',
      );
    });

    it('strips v1 version prefix from path', () => {
      expect(internals.extractEndpoint('https://graph.microsoft.com/v1/me/messages')).toBe(
        '/me/messages',
      );
    });

    it('strips v2.0 version prefix from path', () => {
      expect(internals.extractEndpoint('https://graph.microsoft.com/v2.0/users')).toBe('/users');
    });

    it('extracts endpoint from a Request object', () => {
      const request = new Request('https://graph.microsoft.com/v1.0/me/mailFolders');
      expect(internals.extractEndpoint(request)).toBe('/me/mailFolders');
    });

    it('returns / for root path', () => {
      expect(internals.extractEndpoint('https://graph.microsoft.com/v1.0/')).toBe('/');
    });

    it('returns unknown for an invalid URL', () => {
      expect(internals.extractEndpoint('not-a-url')).toBe('unknown');
    });
  });

  describe('sanitizeEndpointForMetrics', () => {
    it('leaves clean resource names unchanged', () => {
      expect(internals.sanitizeEndpointForMetrics('/me/messages')).toBe('/me/messages');
    });

    it('leaves childFolders unchanged (12 chars, no digit)', () => {
      expect(internals.sanitizeEndpointForMetrics('/me/mailFolders/childFolders')).toBe(
        '/me/mailFolders/childFolders',
      );
    });

    it('replaces a UUID segment', () => {
      expect(
        internals.sanitizeEndpointForMetrics(
          '/users/550e8400-e29b-41d4-a716-446655440000/mailFolders',
        ),
      ).toBe('/users/:id/mailFolders');
    });

    it('replaces a long Outlook base64 ID segment containing a digit', () => {
      const outlookId = 'AAMkADc4ZTM3OWQ4LWJlOGEtNGVjZi1hMjFlLWI4NDE2ZWIyZGUyNgBGAAAAAAB';
      expect(internals.sanitizeEndpointForMetrics(`/me/messages/${outlookId}`)).toBe(
        '/me/messages/:id',
      );
    });

    it('replaces multiple ID segments in one path', () => {
      const folderId = 'AAMkADc4ZTM3OWQ4LWJlOGEtNGVjZi1hMjFlLWI4NDE2ZWIyZGUyNgBGAAAAAAB';
      const messageId = 'AAMkADc4ZTM3OWQ4LWJlOGEtNGVjZi1hMjFlLWI4NDE2ZWIyZGUyNgBGBBBBBBB1';
      expect(
        internals.sanitizeEndpointForMetrics(`/me/mailFolders/${folderId}/messages/${messageId}`),
      ).toBe('/me/mailFolders/:id/messages/:id');
    });

    it('does not replace short alphanumeric segment without digit', () => {
      expect(internals.sanitizeEndpointForMetrics('/me/drive/root')).toBe('/me/drive/root');
    });

    it('preserves empty segments from leading slash', () => {
      expect(internals.sanitizeEndpointForMetrics('/me/messages')).toMatch(/^\/me\/messages/);
    });
  });
});
