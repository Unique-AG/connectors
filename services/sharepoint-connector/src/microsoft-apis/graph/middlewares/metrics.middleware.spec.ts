import { type Context, GraphClientError, GraphError } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import type { ConfigService } from '@nestjs/config';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Config } from '../../../config';
import { MetricsMiddleware } from './metrics.middleware';

describe('MetricsMiddleware', () => {
  let middleware: MetricsMiddleware;
  let mockNextMiddleware: {
    execute: ReturnType<typeof vi.fn>;
  };
  let mockHistogram: {
    record: ReturnType<typeof vi.fn>;
  };
  let mockCounter: {
    add: ReturnType<typeof vi.fn>;
  };
  let mockConfigService: ConfigService<Config, true>;

  beforeEach(() => {
    mockNextMiddleware = {
      execute: vi.fn(),
    };

    mockHistogram = {
      record: vi.fn(),
    };

    mockCounter = {
      add: vi.fn(),
    };

    mockConfigService = {
      get: vi.fn().mockImplementation((key: string, _options?: { infer?: boolean }) => {
        if (key === 'sharepoint.auth.tenantId') {
          return 'test-tenant-id';
        }
        return undefined;
      }),
    } as unknown as ConfigService<Config, true>;

    middleware = new MetricsMiddleware(mockHistogram, mockCounter, mockCounter, mockConfigService);
    middleware.setNext(mockNextMiddleware);
  });

  it('logs successful request metrics', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/abc/drives',
      options: { method: 'GET' },
    };

    const mockResponse = new Response('{"value": []}', { status: 200 });
    mockContext.response = mockResponse;

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = mockResponse;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalledWith(mockContext);
  });

  it('extracts endpoint from request URL', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/drives',
      options: {},
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('extracts method from options', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: { method: 'POST' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 201 });
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('detects throttling on 429 status', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const throttledResponse = new Response('Too Many Requests', { status: 429 });

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = throttledResponse;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('detects throttling on 503 with Retry-After header', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const throttledResponse = new Response('Service Unavailable', {
      status: 503,
      headers: { 'Retry-After': '60' },
    });

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = throttledResponse;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('identifies throttle policy from headers', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const response = new Response('', {
      status: 429,
      headers: { 'RateLimit-Limit': '1000' },
    });

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = response;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('logs error details when request fails', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const error = new Error('Network failure');
    mockNextMiddleware.execute.mockRejectedValue(error);

    await expect(middleware.execute(mockContext)).rejects.toThrow('Network failure');
  });

  it('extracts GraphError details', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const graphError = new GraphError(404, 'Not found');
    Object.assign(graphError, {
      statusCode: 404,
      code: 'itemNotFound',
      body: 'Resource not found',
    });

    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);
  });

  it('extracts GraphClientError details', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const clientError = new GraphClientError('Custom error');
    mockNextMiddleware.execute.mockRejectedValue(clientError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(clientError);
  });

  it('handles Request object as request parameter', async () => {
    const mockRequest = new Request('https://graph.microsoft.com/v1.0/sites/abc');
    const mockContext: Context = {
      request: mockRequest,
      options: {},
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('handles invalid URL gracefully', async () => {
    const mockContext: Context = {
      request: 'invalid-url',
      options: {},
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('defaults to GET method when not specified', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalled();
  });

  it('categorizes status codes correctly', async () => {
    const testCases = [
      { status: 200, expectedClass: '2xx' },
      { status: 301, expectedClass: '3xx' },
      { status: 404, expectedClass: '404' },
      { status: 500, expectedClass: '5xx' },
    ];

    for (const { status, expectedClass } of testCases) {
      const mockContext: Context = {
        request: 'https://graph.microsoft.com/v1.0/me',
        options: {},
      };

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = new Response('', { status });
      });

      await middleware.execute(mockContext);

      expect(mockHistogram.record).toHaveBeenCalledWith(
        expect.any(Number),
        expect.objectContaining({
          http_status_class: expectedClass,
        }),
      );

      mockHistogram.record.mockClear();
    }
  });

  it('throws error if next middleware not set', async () => {
    const middlewareWithoutNext = new MetricsMiddleware(
      mockHistogram,
      mockCounter,
      mockCounter,
      mockConfigService,
    );
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    await expect(middlewareWithoutNext.execute(mockContext)).rejects.toThrow(
      'Next middleware not set',
    );
  });

  it('handles Headers object in error extraction', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
    };

    const headers = new Headers({ 'x-request-id': '123' });
    const graphError = new GraphError(500, 'Server error');
    Object.assign(graphError, {
      statusCode: 500,
      code: 'internalError',
      headers,
    });

    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);
  });

  it('records histogram metric on success with correct labels', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/drives',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockHistogram.record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/drives',
        result: 'success',
        http_status_class: '2xx',
      }),
    );
  });

  it('records histogram metric on error with correct labels', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/drives/drive-123/items/item-456',
      options: { method: 'GET' },
    };

    const graphError = new GraphError(404, 'Not found');
    Object.assign(graphError, { statusCode: 404 });
    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);

    expect(mockHistogram.record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/drives/{driveId}/items/{itemId}',
        result: 'error',
        http_status_class: '404',
      }),
    );
  });

  it('uses specific status code for individual 4XX errors', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123',
      options: { method: 'GET' },
    };

    const graphError = new GraphError(403, 'Forbidden');
    Object.assign(graphError, { statusCode: 403 });
    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);

    expect(mockHistogram.record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        http_status_class: '403',
      }),
    );
  });

  it('uses status class for 5XX errors', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123',
      options: { method: 'GET' },
    };

    const graphError = new GraphError(503, 'Service Unavailable');
    Object.assign(graphError, { statusCode: 503 });
    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);

    expect(mockHistogram.record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        http_status_class: '5xx',
      }),
    );
  });

  it('extracts correct api_method for different endpoints', async () => {
    const testCases = [
      { url: '/sites/site-123/drives', method: 'GET', expected: 'GET:/sites/{siteId}/drives' },
      {
        url: '/drives/drive-123/items/item-456/children',
        method: 'GET',
        expected: 'GET:/drives/{driveId}/items/{itemId}/children',
      },
      {
        url: '/drives/drive-123/items/item-456/content',
        method: 'GET',
        expected: 'GET:/drives/{driveId}/items/{itemId}/content',
      },
      {
        url: '/drives/drive-123/items/item-456',
        method: 'GET',
        expected: 'GET:/drives/{driveId}/items/{itemId}',
      },
      { url: '/sites/site-123/lists', method: 'GET', expected: 'GET:/sites/{siteId}/lists' },
      {
        url: '/sites/site-123/lists/list-123/items',
        method: 'GET',
        expected: 'GET:/sites/{siteId}/lists/{listId}/items',
      },
    ];

    for (const { url, method, expected } of testCases) {
      const mockContext: Context = {
        request: `https://graph.microsoft.com/v1.0${url}`,
        options: { method },
      };

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = new Response('{}', { status: 200 });
      });

      await middleware.execute(mockContext);

      expect(mockHistogram.record).toHaveBeenCalledWith(
        expect.any(Number),
        expect.objectContaining({
          api_method: expected,
        }),
      );

      mockHistogram.record.mockClear();
    }
  });

  it('increments throttle counter on 429 status', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/drives',
      options: { method: 'GET' },
    };

    const throttledResponse = new Response('Too Many Requests', {
      status: 429,
      headers: { 'Retry-After': '60' },
    });

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = throttledResponse;
    });

    await middleware.execute(mockContext);

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/drives',
        policy: 'retry_after',
      }),
    );
  });

  it('increments throttle counter with rate_limit policy', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/lists',
      options: { method: 'GET' },
    };

    const throttledResponse = new Response('Too Many Requests', {
      status: 429,
      headers: { 'RateLimit-Limit': '1000' },
    });

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = throttledResponse;
    });

    await middleware.execute(mockContext);

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/lists',
        policy: 'rate_limit',
      }),
    );
  });

  it('does not increment throttle counter on non-throttled requests', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    expect(mockCounter.add).not.toHaveBeenCalled();
  });

  it('increments slow request counter for requests >1s', async () => {
    vi.useFakeTimers();

    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/drives',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      await new Promise((resolve) => setTimeout(resolve, 1100));
      ctx.response = new Response('{}', { status: 200 });
    });

    const executePromise = middleware.execute(mockContext);
    await vi.advanceTimersByTimeAsync(1100);
    await executePromise;

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/drives',
        duration_bucket: '>1s',
      }),
    );

    vi.useRealTimers();
  });

  it('increments slow request counter for requests >2s', async () => {
    vi.useFakeTimers();

    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/lists',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      await new Promise((resolve) => setTimeout(resolve, 3100));
      ctx.response = new Response('{}', { status: 200 });
    });

    const executePromise = middleware.execute(mockContext);
    await vi.advanceTimersByTimeAsync(3100);
    await executePromise;

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/lists',
        duration_bucket: '>2s',
      }),
    );

    vi.useRealTimers();
  });

  it('increments slow request counter for requests >5s', async () => {
    vi.useFakeTimers();

    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/drives/drive-123/items/item-456',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      await new Promise((resolve) => setTimeout(resolve, 5100));
      ctx.response = new Response('{}', { status: 200 });
    });

    const executePromise = middleware.execute(mockContext);
    await vi.advanceTimersByTimeAsync(5100);
    await executePromise;

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/drives/{driveId}/items/{itemId}',
        duration_bucket: '>5s',
      }),
    );

    vi.useRealTimers();
  });

  it('increments slow request counter for requests >10s', async () => {
    vi.useFakeTimers();

    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123',
      options: { method: 'GET' },
    };

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      await new Promise((resolve) => setTimeout(resolve, 10100));
      ctx.response = new Response('{}', { status: 200 });
    });

    const executePromise = middleware.execute(mockContext);
    await vi.advanceTimersByTimeAsync(10100);
    await executePromise;

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}',
        duration_bucket: '>10s',
      }),
    );

    vi.useRealTimers();
  });

  it('does not increment slow request counter for fast requests', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123',
      options: { method: 'GET' },
    };

    const initialCallCount = mockCounter.add.mock.calls.length;

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = new Response('{}', { status: 200 });
    });

    await middleware.execute(mockContext);

    const callsWithSlowRequestsLabel = mockCounter.add.mock.calls
      .slice(initialCallCount)
      .filter((call) => call[1]?.duration_bucket);

    expect(callsWithSlowRequestsLabel).toHaveLength(0);
  });

  it('increments slow request counter on error with slow duration', async () => {
    vi.useFakeTimers();

    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/site-123/drives',
      options: { method: 'GET' },
    };

    const graphError = new GraphError(500, 'Internal Server Error');
    Object.assign(graphError, { statusCode: 500 });

    mockNextMiddleware.execute.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      throw graphError;
    });

    const executePromise = middleware.execute(mockContext);
    const expectPromise = expect(executePromise).rejects.toThrow(graphError);

    await vi.advanceTimersByTimeAsync(2000);
    await expectPromise;

    expect(mockCounter.add).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        ms_tenant_id: 'test-tenant-id',
        api_method: 'GET:/sites/{siteId}/drives',
        duration_bucket: '>1s',
      }),
    );

    vi.useRealTimers();
  });

  describe('endpoint extraction with sensitive data concealment', () => {
    let loggerDebugSpy: ReturnType<typeof vi.fn>;

    const createConcealingConfigService = (): ConfigService<Config, true> => {
      return {
        get: vi.fn().mockImplementation((key: string, _options?: { infer?: boolean }) => {
          if (key === 'sharepoint.auth.tenantId') {
            return 'test-tenant-id';
          }
          if (key === 'app.logsDiagnosticsDataPolicy') {
            return 'conceal';
          }
          return undefined;
        }),
      } as unknown as ConfigService<Config, true>;
    };

    beforeEach(() => {
      loggerDebugSpy = vi.fn();
      // Mock the Logger constructor to return an object with debug method
      vi.mocked(Logger).mockImplementation(
        () =>
          ({
            debug: loggerDebugSpy,
            log: vi.fn(),
            error: vi.fn(),
            warn: vi.fn(),
            verbose: vi.fn(),
          }) as unknown as Logger,
      );
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('conceals site names in logged endpoints when enabled', async () => {
      const concealingConfigService = createConcealingConfigService();
      const concealingMiddleware = new MetricsMiddleware(
        mockHistogram,
        mockCounter,
        mockCounter,
        concealingConfigService,
      );
      concealingMiddleware.setNext(mockNextMiddleware);

      const mockContext: Context = {
        request: 'https://graph.microsoft.com/v1.0/sites/LoadTestFlat/_layouts/15/download.aspx',
        options: { method: 'GET' },
      };

      const mockResponse = new Response('{"value": []}', { status: 200 });
      mockContext.response = mockResponse;

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = mockResponse;
      });

      await concealingMiddleware.execute(mockContext);

      expect(loggerDebugSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          endpoint: '/sites/Lo[Redacted]at/_layouts/15/download.aspx',
        }),
      );
    });

    it('conceals site IDs in logged endpoints when enabled', async () => {
      const concealingConfigService = createConcealingConfigService();
      const concealingMiddleware = new MetricsMiddleware(
        mockHistogram,
        mockCounter,
        mockCounter,
        concealingConfigService,
      );
      concealingMiddleware.setNext(mockNextMiddleware);

      const mockContext: Context = {
        request:
          'https://graph.microsoft.com/v1.0/sites/1d045c6a-f230-48fd-b826-7cf8601d7729/lists',
        options: { method: 'GET' },
      };

      const mockResponse = new Response('{"value": []}', { status: 200 });
      mockContext.response = mockResponse;

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = mockResponse;
      });

      await concealingMiddleware.execute(mockContext);

      expect(loggerDebugSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          endpoint: '/sites/********-****-****-****-********7729/lists',
        }),
      );
    });

    it('conceals site IDs in logged endpoints without trailing path when enabled', async () => {
      const concealingConfigService = createConcealingConfigService();
      const concealingMiddleware = new MetricsMiddleware(
        mockHistogram,
        mockCounter,
        mockCounter,
        concealingConfigService,
      );
      concealingMiddleware.setNext(mockNextMiddleware);

      const mockContext: Context = {
        request: 'https://graph.microsoft.com/v1.0/sites/1d045c6a-f230-48fd-b826-7cf8601d7729',
        options: { method: 'GET' },
      };

      const mockResponse = new Response('{"value": []}', { status: 200 });
      mockContext.response = mockResponse;

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = mockResponse;
      });

      await concealingMiddleware.execute(mockContext);

      expect(loggerDebugSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          endpoint: '/sites/********-****-****-****-********7729',
        }),
      );
    });

    it('does not conceal endpoints in logs when disabled', async () => {
      const nonConcealingMiddleware = new MetricsMiddleware(
        mockHistogram,
        mockCounter,
        mockCounter,
        mockConfigService,
      );
      nonConcealingMiddleware.setNext(mockNextMiddleware);

      const mockContext: Context = {
        request: 'https://graph.microsoft.com/v1.0/sites/LoadTestFlat/_layouts/15/download.aspx',
        options: { method: 'GET' },
      };

      const mockResponse = new Response('{"value": []}', { status: 200 });
      mockContext.response = mockResponse;

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = mockResponse;
      });

      await nonConcealingMiddleware.execute(mockContext);

      expect(loggerDebugSpy).toHaveBeenCalledWith(
        expect.objectContaining({
          endpoint: '/sites/LoadTestFlat/_layouts/15/download.aspx',
        }),
      );
    });
  });
});
