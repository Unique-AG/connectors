import type { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TemenosConfig } from '~/config';
import type { Metrics } from './metrics';

vi.mock('undici', () => ({
  request: vi.fn(),
}));

import { request } from 'undici';
import { TemenosApiError, TemenosHttpClient } from './temenos-http.client';

const mockRecorder: Pick<Metrics, 'recordApiRequest'> = {
  recordApiRequest: vi.fn(),
};

const stubConfig = { apiBaseUrl: 'https://api.example.com', apiKey: { value: 'key' } };
const mockedRequest = vi.mocked(request);

function mockResponse(statusCode: number, body: string): Dispatcher.ResponseData {
  // The client reads via `for await (const chunk of response.body)` so the
  // mock must expose an async iterator over Buffer chunks.
  return {
    statusCode,
    headers: {},
    body: {
      async *[Symbol.asyncIterator]() {
        if (body.length > 0) {
          yield Buffer.from(body, 'utf-8');
        }
      },
    },
  } as unknown as Dispatcher.ResponseData;
}

describe('TemenosHttpClient', () => {
  let unit: TemenosHttpClient;

  beforeEach(() => {
    vi.clearAllMocks();
    unit = new TemenosHttpClient(stubConfig as TemenosConfig, mockRecorder as unknown as Metrics);
  });

  describe('get', () => {
    it('builds the request URL, forwards the apikey header, and records metrics', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(200, JSON.stringify({ ok: true })));

      const result = await unit.get<{ ok: boolean }>('/party/v1.0.0/parties', {
        customerId: 'PTY-0002001',
        unused: undefined,
      });

      expect(result).toEqual({ ok: true });
      expect(mockedRequest).toHaveBeenCalledWith(
        'https://api.example.com/party/v1.0.0/parties?customerId=PTY-0002001',
        {
          method: 'GET',
          headers: {
            apikey: 'key',
            Accept: 'application/json',
          },
        },
      );
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        path: '/party/v1.0.0/parties',
        status: 200,
        durationMs: expect.any(Number),
      });
    });

    it('returns undefined for empty successful responses', async () => {
      mockedRequest.mockResolvedValueOnce(mockResponse(204, ''));

      const result = await unit.get('/reference/v1.0.0/countries');

      expect(result).toBeUndefined();
    });

    it('throws TemenosApiError carrying status, path, and the message from the error body', async () => {
      mockedRequest.mockResolvedValueOnce(
        mockResponse(404, JSON.stringify({ message: 'Party not found' })),
      );

      await expect(unit.get('/party/v1.0.0/parties/UNKNOWN')).rejects.toMatchObject({
        name: 'TemenosApiError',
        status: 404,
        path: '/party/v1.0.0/parties/UNKNOWN',
        message: 'Party not found',
      } satisfies Partial<TemenosApiError>);

      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        path: '/party/v1.0.0/parties/UNKNOWN',
        status: 404,
        durationMs: expect.any(Number),
      });
    });

    it('returns a generic HTTP message when the error payload has no known field', async () => {
      // Raw upstream text is intentionally not echoed into the error message:
      // a Temenos response without a documented error field could contain
      // arbitrary content (HTML, stack traces, customer data) that must not
      // leak via the thrown error or the catch-block log.
      mockedRequest.mockResolvedValueOnce(mockResponse(500, 'upstream exploded'));

      await expect(unit.get('/reference/v1.0.0/lookups')).rejects.toMatchObject({
        name: 'TemenosApiError',
        status: 500,
        message: 'HTTP 500',
      } satisfies Partial<TemenosApiError>);
    });

    it('throws when the response body exceeds the size cap', async () => {
      // 11 MB > the 10 MB cap defined in TemenosHttpClient.MAX_RESPONSE_BYTES.
      // The streaming reader must bail before buffering the full payload.
      const oversized = 'x'.repeat(11 * 1024 * 1024);
      mockedRequest.mockResolvedValueOnce(mockResponse(200, oversized));

      await expect(unit.get('/reference/v1.0.0/lookups')).rejects.toThrow(/exceeded/);
    });

    it('rethrows transport errors after logging and still records metrics with status 0', async () => {
      const error = new Error('ECONNRESET');
      mockedRequest.mockRejectedValueOnce(error);

      await expect(unit.get('/reference/v1.0.0/countries')).rejects.toThrow('ECONNRESET');
      expect(mockRecorder.recordApiRequest).toHaveBeenCalledWith({
        path: '/reference/v1.0.0/countries',
        status: 0,
        durationMs: expect.any(Number),
      });
    });
  });
});
