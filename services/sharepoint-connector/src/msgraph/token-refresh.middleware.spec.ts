import type { Context } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphAuthenticationProvider } from './graph-authentication.service';
import { TokenRefreshMiddleware } from './token-refresh.middleware';

describe('TokenRefreshMiddleware', () => {
  let middleware: TokenRefreshMiddleware;
  let mockAuthProvider: {
    getAccessToken: ReturnType<typeof vi.fn>;
  };
  let mockNextMiddleware: {
    execute: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    mockAuthProvider = {
      getAccessToken: vi.fn().mockResolvedValue('new-token-123'),
    };

    mockNextMiddleware = {
      execute: vi.fn(),
    };

    middleware = new TokenRefreshMiddleware(mockAuthProvider as never);
    middleware.setNext(mockNextMiddleware as never);
  });

  it('passes through successful requests without retry', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const mockResponse = new Response('{"value": "test"}', { status: 200 });
    mockContext.response = mockResponse;

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = mockResponse;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalledTimes(1);
    expect(mockAuthProvider.getAccessToken).not.toHaveBeenCalled();
  });

  it('retries request with new token on 401 with expired token error', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: { headers: { Authorization: 'Bearer old-token' } },
      middlewareControl: {} as never,
    };

    const expiredResponse = new Response(
      JSON.stringify({
        error: {
          code: 'InvalidAuthenticationToken',
          message: 'Access token has expired',
        },
      }),
      { status: 401 },
    );

    const successResponse = new Response('{"value": "test"}', { status: 200 });

    mockNextMiddleware.execute
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = expiredResponse;
      })
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = successResponse;
      });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalledTimes(2);
    expect(mockAuthProvider.getAccessToken).toHaveBeenCalledTimes(1);
    expect(mockContext.response).toBe(successResponse);
  });

  it('updates authorization header with new token on retry', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: { headers: { Authorization: 'Bearer old-token' } },
      middlewareControl: {} as never,
    };

    const expiredResponse = new Response(
      JSON.stringify({ error: { code: 'InvalidAuthenticationToken' } }),
      { status: 401 },
    );

    mockNextMiddleware.execute
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = expiredResponse;
      })
      .mockImplementationOnce(async (ctx: Context) => {
        expect(ctx.options?.headers).toHaveProperty('Authorization', 'Bearer new-token-123');
        ctx.response = new Response('{}', { status: 200 });
      });

    await middleware.execute(mockContext);

    expect(mockAuthProvider.getAccessToken).toHaveBeenCalled();
  });

  it('detects token expiration from error message', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const expiredResponse = new Response(
      JSON.stringify({
        error: { message: 'Lifetime validation failed. The token is expired.' },
      }),
      { status: 401 },
    );

    mockNextMiddleware.execute
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = expiredResponse;
      })
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = new Response('{}', { status: 200 });
      });

    await middleware.execute(mockContext);

    expect(mockAuthProvider.getAccessToken).toHaveBeenCalled();
  });

  it('does not retry on 401 without token expiration indicators', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const unauthorizedResponse = new Response(
      JSON.stringify({ error: { message: 'Insufficient permissions' } }),
      { status: 401 },
    );

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = unauthorizedResponse;
    });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalledTimes(1);
    expect(mockAuthProvider.getAccessToken).not.toHaveBeenCalled();
  });

  it('handles non-JSON 401 responses', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const unauthorizedResponse = new Response('Unauthorized', { status: 401 });

    mockNextMiddleware.execute
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = unauthorizedResponse;
      })
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = new Response('{}', { status: 200 });
      });

    await middleware.execute(mockContext);

    expect(mockAuthProvider.getAccessToken).toHaveBeenCalled();
  });

  it('handles token refresh failure gracefully', async () => {
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    const expiredResponse = new Response(
      JSON.stringify({ error: { code: 'InvalidAuthenticationToken' } }),
      { status: 401 },
    );

    mockNextMiddleware.execute.mockImplementation(async (ctx: Context) => {
      ctx.response = expiredResponse;
    });

    mockAuthProvider.getAccessToken.mockRejectedValue(new Error('Token refresh failed'));

    await middleware.execute(mockContext);

    expect(mockContext.response).toBe(expiredResponse);
  });

  it('throws error if next middleware is not set', async () => {
    const middlewareWithoutNext = new TokenRefreshMiddleware(mockAuthProvider as never);
    const mockContext: Context = {
      request: 'https://graph.microsoft.com/v1.0/me',
      options: {},
      middlewareControl: {} as never,
    };

    await expect(middlewareWithoutNext.execute(mockContext)).rejects.toThrow(
      'Next middleware not set',
    );
  });

  it('clones request object before retry', async () => {
    const mockRequest = new Request('https://graph.microsoft.com/v1.0/me');
    const mockContext: Context = {
      request: mockRequest,
      options: {},
      middlewareControl: {} as never,
    };

    const expiredResponse = new Response(
      JSON.stringify({ error: { code: 'InvalidAuthenticationToken' } }),
      { status: 401 },
    );

    mockNextMiddleware.execute
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = expiredResponse;
      })
      .mockImplementationOnce(async (ctx: Context) => {
        ctx.response = new Response('{}', { status: 200 });
      });

    await middleware.execute(mockContext);

    expect(mockNextMiddleware.execute).toHaveBeenCalledTimes(2);
  });
});


