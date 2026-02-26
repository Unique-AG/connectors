import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';

vi.mock('undici', () => ({
  Agent: class MockAgent {
    public compose() {
      return {};
    }
  },
  interceptors: { redirect: () => ({}), retry: () => ({}) },
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
import { RateLimitedHttpClient } from '../rate-limited-http-client';

const mockedRequest = request as Mock;

const mockLogger = {
  info: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
  child: vi.fn(),
};

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
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('RateLimitedHttpClient', () => {
  let client: RateLimitedHttpClient;

  beforeEach(() => {
    vi.clearAllMocks();
    client = new RateLimitedHttpClient(mockLogger as never, 100);
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
