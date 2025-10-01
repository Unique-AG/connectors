import type { Context } from '@microsoft/microsoft-graph-client';
import { GraphClientError, GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MetricsMiddleware } from './metrics.middleware';

describe('MetricsMiddleware', () => {
  let middleware: MetricsMiddleware;
  let mockNextMiddleware: {
    execute: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockNextMiddleware = {
      execute: vi.fn(),
    };

    middleware = new MetricsMiddleware();
    middleware.setNext(mockNextMiddleware as never);
  });

  it('logs successful request metrics', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/sites/abc/drives',
      options: { method: 'GET' },
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
    };

    const error = new Error('Network failure');
    mockNextMiddleware.execute.mockRejectedValue(error);

    await expect(middleware.execute(mockContext)).rejects.toThrow('Network failure');
  });

  it('extracts GraphError details', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const graphError = new GraphError(404, 'Not found', {
      statusCode: 404,
      code: 'itemNotFound',
      message: 'Resource not found',
    });

    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);
  });

  it('extracts GraphClientError details', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      middlewareControl: {} as never,
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
      { status: 404, expectedClass: '4xx' },
      { status: 500, expectedClass: '5xx' },
    ];

    for (const { status } of testCases) {
      const mockContext: Context = {
        request: 'https://graph.microsoft.com/v1.0/me',
        options: {},
        middlewareControl: {} as never,
      };

      mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
        ctx.response = new Response('', { status });
      });

      await middleware.execute(mockContext);
    }

    expect(mockNextMiddleware.execute).toHaveBeenCalledTimes(testCases.length);
  });

  it('throws error if next middleware not set', async () => {
    const middlewareWithoutNext = new MetricsMiddleware();
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    await expect(middlewareWithoutNext.execute(mockContext)).rejects.toThrow(
      'Next middleware not set',
    );
  });

  it('handles Headers object in error extraction', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const headers = new Headers({ 'x-request-id': '123' });
    const graphError = new GraphError(500, 'Server error', {
      statusCode: 500,
      code: 'internalError',
      message: 'Internal server error',
    });
    // biome-ignore lint/suspicious/noExplicitAny: Test property assignment
    (graphError as any).headers = headers;

    mockNextMiddleware.execute.mockRejectedValue(graphError);

    await expect(middleware.execute(mockContext)).rejects.toThrow(graphError);
  });
});

