/** biome-ignore-all lint/suspicious/noExplicitAny: Mock TokenProvider and read the private logger */
import {
  isUpstreamCredentialRevokedError,
  UpstreamCredentialRevokedError,
} from '@unique-ag/mcp-oauth';
import {
  Client,
  type Context,
  GraphError,
  type Middleware,
} from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { isTokenExpiredError } from '../../utils/is-token-expired-error';
import { TokenRefreshCoolingDownError } from '../token.provider';
import { TokenRefreshMiddleware } from '../token-refresh.middleware';

const GRAPH_URL =
  'https://graph.microsoft.com/v1.0/users/jane.doe@contoso.example/messages?$top=1&$select=id';

const graphResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const expiredTokenResponse = () =>
  graphResponse(401, { error: { code: 'InvalidAuthenticationToken', message: 'expired' } });

const accessDeniedResponse = () =>
  graphResponse(403, {
    error: {
      code: 'ErrorAccessDenied',
      message: 'Access to jane.doe@contoso.example is denied.',
      innerError: { 'request-id': 'request-id-value', 'client-request-id': 'client-request-id' },
    },
  });

describe('TokenRefreshMiddleware', () => {
  let tokenProvider: { refreshAccessToken: ReturnType<typeof vi.fn> };
  let unit: TokenRefreshMiddleware;
  let next: { execute: ReturnType<typeof vi.fn> };

  const createContext = (): Context => ({
    request: GRAPH_URL,
    options: { method: 'GET', headers: { Authorization: 'Bearer rejected-access-token' } },
  });

  const respondWith = (...responses: Response[]) => {
    for (const response of responses) {
      next.execute.mockImplementationOnce(async (context: Context) => {
        context.response = response;
      });
    }
  };

  beforeEach(() => {
    tokenProvider = { refreshAccessToken: vi.fn().mockResolvedValue('new-access-token') };
    next = { execute: vi.fn() };
    unit = new TokenRefreshMiddleware(tokenProvider as any, 'user-profile-123');
    unit.setNext(next as unknown as Middleware);
  });

  it('passes the access token Graph rejected to the refresh', async () => {
    respondWith(expiredTokenResponse(), graphResponse(200, { value: [] }));

    await unit.execute(createContext());

    expect(tokenProvider.refreshAccessToken).toHaveBeenCalledWith(
      'user-profile-123',
      'rejected-access-token',
    );
  });

  it('retries with the refreshed access token', async () => {
    respondWith(expiredTokenResponse(), graphResponse(200, { value: [] }));
    const context = createContext();

    await unit.execute(context);

    expect(next.execute).toHaveBeenLastCalledWith(
      expect.objectContaining({
        options: expect.objectContaining({
          headers: { Authorization: 'Bearer new-access-token' },
        }),
      }),
    );
    expect(context.response?.status).toBe(200);
  });

  it('logs the status, Graph error code, method and path of a failed retry', async () => {
    respondWith(expiredTokenResponse(), accessDeniedResponse());

    await unit.execute(createContext());

    expect((unit as any).logger.warn).toHaveBeenCalledWith({
      msg: 'Microsoft Graph request failed even after successful token refresh',
      userProfileId: 'user-profile-123',
      retryResult: 'failed',
      tokenRefreshWorked: false,
      retryStatus: 403,
      graphErrorCode: 'ErrorAccessDenied',
      method: 'GET',
      path: '/users/:id/messages',
    });
  });

  it('keeps mailbox addresses, request ids and tokens out of the failed retry log', async () => {
    respondWith(expiredTokenResponse(), accessDeniedResponse());

    await unit.execute(createContext());

    const logged = JSON.stringify((unit as any).logger.warn.mock.calls);
    expect(logged).not.toContain('jane.doe@contoso.example');
    expect(logged).not.toContain('request-id-value');
    expect(logged).not.toContain('client-request-id');
    expect(logged).not.toContain('access-token');
  });

  it('keeps the 401 without retrying while the refresh is backing off', async () => {
    respondWith(expiredTokenResponse());
    tokenProvider.refreshAccessToken.mockRejectedValue(
      new TokenRefreshCoolingDownError(new Date('2026-11-24T00:01:00.000Z')),
    );
    const context = createContext();

    await unit.execute(context);

    expect(context.response?.status).toBe(401);
    expect(next.execute).toHaveBeenCalledTimes(1);
    expect((unit as any).logger.error).not.toHaveBeenCalled();
  });

  it('keeps a revoked grant recognisable after the Graph SDK wraps it', async () => {
    respondWith(expiredTokenResponse());
    tokenProvider.refreshAccessToken.mockRejectedValue(
      new UpstreamCredentialRevokedError('AADSTS70000: Provided grant is invalid or malformed.'),
    );
    const client = Client.initWithMiddleware({ middleware: unit });

    const error = await client
      .api('/users/jane.doe@contoso.example/messages')
      .get()
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(GraphError);
    expect(isUpstreamCredentialRevokedError(error)).toBe(true);
    expect(isTokenExpiredError(error)).toBe(true);
  });

  it('does not refresh when Graph does not answer 401', async () => {
    respondWith(accessDeniedResponse());

    await unit.execute(createContext());

    expect(tokenProvider.refreshAccessToken).not.toHaveBeenCalled();
  });
});
