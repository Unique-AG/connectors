import { Readable } from 'node:stream';
import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';

vi.mock('undici', () => ({
  Agent: class MockAgent {
    public compose(composed: string[]) {
      return { composed };
    }
  },
  interceptors: { redirect: () => 'redirect', retry: () => 'retry' },
  request: vi.fn(),
}));

const mockBottleneckOn = vi.fn();
const mockBottleneckSchedule = vi.fn(<T>(fn: () => Promise<T>) => fn());

vi.mock('bottleneck', () => ({
  default: class MockBottleneck {
    public on = mockBottleneckOn;
    public schedule = mockBottleneckSchedule;
  },
}));

import { request } from 'undici';
import { createNoopMetrics } from '../../metrics/__mocks__/noop-metrics';
import { RateLimitedHttpClient } from '../rate-limited-http-client';

const mockedRequest = request as Mock;

function mockUndiciResponse(
  statusCode: number,
  body: unknown,
  headers: Record<string, string> = {},
): Dispatcher.ResponseData {
  return {
    statusCode,
    headers,
    body: {
      json: vi.fn().mockResolvedValue(body),
      text: vi.fn().mockResolvedValue(JSON.stringify(body)),
      dump: vi.fn().mockResolvedValue(undefined),
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('RateLimitedHttpClient', () => {
  let client: RateLimitedHttpClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new RateLimitedHttpClient(100, createNoopMetrics());
  });

  describe('rateLimitedRequest', () => {
    it('passes headers to undici request', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { ok: true }));

      await client.rateLimitedRequest('https://example.com', {
        Authorization: 'Bearer token',
      });

      expect(mockedRequest).toHaveBeenCalledWith(
        'https://example.com',
        expect.objectContaining({
          headers: { Authorization: 'Bearer token' },
        }),
      );
    });

    it('returns parsed JSON body', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, { data: 'value' }));

      const result = await client.rateLimitedRequest('https://example.com', {});

      expect(result).toEqual({ data: 'value' });
    });

    it('throws on non-2xx status codes', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(403, 'Forbidden'));

      await expect(client.rateLimitedRequest('https://example.com', {})).rejects.toThrow(
        /Error response from/,
      );
    });

    it('includes status code in error message', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(500, 'Server Error'));

      await expect(client.rateLimitedRequest('https://example.com', {})).rejects.toThrow(/500/);
    });

    it('follows same-origin redirects with the credentials intact', async () => {
      mockedRequest
        .mockResolvedValueOnce(
          mockUndiciResponse(302, '', { location: '/confluence/rest/api/content' }),
        )
        .mockResolvedValueOnce(mockUndiciResponse(200, { data: 'value' }));

      const result = await client.rateLimitedRequest('https://example.com/rest/api/content', {
        Authorization: 'Basic dXNlcjpwYXNz',
      });

      expect(result).toEqual({ data: 'value' });
      expect(mockedRequest).toHaveBeenLastCalledWith(
        'https://example.com/confluence/rest/api/content',
        expect.objectContaining({ headers: { Authorization: 'Basic dXNlcjpwYXNz' } }),
      );
    });

    it('rejects a cross-origin redirect instead of continuing unauthenticated', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(302, '', { location: 'https://other.example.com/rest/api/content' }),
      );

      await expect(
        client.rateLimitedRequest('https://example.com/rest/api/content', {
          Authorization: 'Basic dXNlcjpwYXNz',
        }),
      ).rejects.toThrow(/redirected to a different origin \(https:\/\/other\.example\.com\)/);

      expect(mockedRequest).toHaveBeenCalledTimes(1);
    });

    it('rejects a scheme-only redirect because it also drops credentials', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(301, '', { location: 'https://example.com/rest/api/content' }),
      );

      await expect(
        client.rateLimitedRequest('http://example.com/rest/api/content', {}),
      ).rejects.toThrow(/redirected to a different origin/);
    });
  });

  describe('rateLimitedStreamRequest', () => {
    it('passes headers to undici request', async () => {
      const mockBody = new Readable({ read() {} });
      mockedRequest.mockResolvedValueOnce(
        mockUndiciResponse(200, mockBody) as unknown as Dispatcher.ResponseData,
      );

      await client.rateLimitedStreamRequest('https://example.com/download', {
        Authorization: 'Bearer token',
      });

      expect(mockedRequest).toHaveBeenCalledWith(
        'https://example.com/download',
        expect.objectContaining({
          headers: { Authorization: 'Bearer token' },
        }),
      );
    });

    it('returns the response body as a Readable stream', async () => {
      const mockStream = new Readable({ read() {} });
      const response = {
        statusCode: 200,
        headers: {},
        body: Object.assign(mockStream, {
          json: vi.fn(),
          text: vi.fn(),
        }),
      } as unknown as Dispatcher.ResponseData;
      mockedRequest.mockResolvedValueOnce(response);

      const result = await client.rateLimitedStreamRequest('https://example.com/download', {});

      expect(result).toBe(response.body);
      expect(result).toBeInstanceOf(Readable);
    });

    it('throws on non-2xx status codes', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(404, 'Not Found'));

      await expect(
        client.rateLimitedStreamRequest('https://example.com/download', {}),
      ).rejects.toThrow(/Error response from/);
    });

    // Cloud attachment downloads redirect to a presigned media URL on another origin, which only
    // works when undici follows the redirect and drops the Authorization header.
    it('uses the redirect-following dispatcher', async () => {
      mockedRequest.mockResolvedValueOnce(mockUndiciResponse(200, new Readable({ read() {} })));

      await client.rateLimitedStreamRequest('https://example.com/download', {});

      expect(mockedRequest).toHaveBeenCalledWith(
        'https://example.com/download',
        expect.objectContaining({ dispatcher: { composed: ['redirect', 'retry'] } }),
      );
    });
  });

  describe('throttle monitoring', () => {
    it('registers depleted, dropped, and error event handlers', () => {
      const registeredEvents = mockBottleneckOn.mock.calls.map((call) => call[0]);
      expect(registeredEvents).toContain('depleted');
      expect(registeredEvents).toContain('dropped');
      expect(registeredEvents).toContain('error');
    });
  });
});
