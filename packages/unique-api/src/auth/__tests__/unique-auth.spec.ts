import assert from 'node:assert';

import { type MockInstance, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Dispatcher } from 'undici';

import type { UniqueApiMetrics } from '../../core/observability';
import type { ClusterLocalAuthConfig, ExternalAuthConfig } from '../../core/types';
import { UniqueAuth } from '../unique-auth';

function createMockMetrics(): UniqueApiMetrics {
  return {
    authTokenRefreshTotal: { add: vi.fn() },
    requestsTotal: { add: vi.fn() },
    errorsTotal: { add: vi.fn() },
    requestDurationMs: { record: vi.fn() },
    slowRequestsTotal: { add: vi.fn() },
  } as unknown as UniqueApiMetrics;
}

function createMockLogger() {
  return { error: vi.fn(), debug: vi.fn() };
}

function createDispatcherResponse(
  statusCode: number,
  body: object,
): Dispatcher.ResponseData {
  return {
    statusCode,
    headers: {},
    body: {
      text: () => Promise.resolve(JSON.stringify(body)),
      json: () => Promise.resolve(body),
    },
  } as unknown as Dispatcher.ResponseData;
}

const externalConfig: ExternalAuthConfig = {
  mode: 'external',
  zitadelOauthTokenUrl: 'https://zitadel.example.com/oauth/v2/token',
  zitadelClientId: 'client-id',
  zitadelClientSecret: 'client-secret',
  zitadelProjectId: 'project-id',
};

const clusterLocalConfig: ClusterLocalAuthConfig = {
  mode: 'cluster_local',
  serviceId: 'my-service',
  extraHeaders: { 'x-custom': 'value' },
};

describe('UniqueAuth', () => {
  let metrics: UniqueApiMetrics;
  let logger: ReturnType<typeof createMockLogger>;
  let dispatcher: { request: MockInstance };

  beforeEach(() => {
    metrics = createMockMetrics();
    logger = createMockLogger();
    dispatcher = { request: vi.fn() };
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe('cluster_local mode', () => {
    it('returns x-service-id and extra headers from getAuthHeaders()', async () => {
      const auth = new UniqueAuth({
        config: clusterLocalConfig,
        metrics,
        logger,
        dispatcher: dispatcher as unknown as Dispatcher,
      });

      const headers = await auth.getAuthHeaders();

      expect(headers).toStrictEqual({
        'x-service-id': 'my-service',
        'x-custom': 'value',
      });
    });

    it('throws assertion error when getToken() is called', async () => {
      const auth = new UniqueAuth({
        config: clusterLocalConfig,
        metrics,
        logger,
        dispatcher: dispatcher as unknown as Dispatcher,
      });

      await expect(auth.getToken()).rejects.toThrow(assert.AssertionError);
    });
  });

  describe('external mode', () => {
    function createExternalAuth() {
      return new UniqueAuth({
        config: externalConfig,
        metrics,
        logger,
        dispatcher: dispatcher as unknown as Dispatcher,
      });
    }

    it('fetches token from Zitadel and caches it', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(200, {
          access_token: 'token-abc',
          expires_in: 3600,
        }),
      );

      const auth = createExternalAuth();
      const token = await auth.getToken();

      expect(token).toBe('token-abc');
      expect(dispatcher.request).toHaveBeenCalledOnce();
      expect(dispatcher.request).toHaveBeenCalledWith(
        expect.objectContaining({
          origin: 'https://zitadel.example.com',
          path: '/oauth/v2/token',
          method: 'POST',
        }),
      );
      expect(metrics.authTokenRefreshTotal.add).toHaveBeenCalledWith(1);
    });

    it('returns cached token on second call without fetching again', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(200, {
          access_token: 'token-abc',
          expires_in: 3600,
        }),
      );

      const auth = createExternalAuth();

      const first = await auth.getToken();
      const second = await auth.getToken();

      expect(first).toBe('token-abc');
      expect(second).toBe('token-abc');
      expect(dispatcher.request).toHaveBeenCalledOnce();
    });

    it('fetches a new token after the cached one expires', async () => {
      vi.useFakeTimers();

      dispatcher.request
        .mockResolvedValueOnce(
          createDispatcherResponse(200, {
            access_token: 'token-1',
            expires_in: 60,
          }),
        )
        .mockResolvedValueOnce(
          createDispatcherResponse(200, {
            access_token: 'token-2',
            expires_in: 60,
          }),
        );

      const auth = createExternalAuth();

      const first = await auth.getToken();
      expect(first).toBe('token-1');

      vi.advanceTimersByTime(61_000);

      const second = await auth.getToken();
      expect(second).toBe('token-2');
      expect(dispatcher.request).toHaveBeenCalledTimes(2);
    });

    it('throws and logs error when fetch fails', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(401, { error: 'unauthorized' }),
      );

      const auth = createExternalAuth();

      await expect(auth.getToken()).rejects.toThrow(
        'Zitadel token request failed with status 401',
      );
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'Failed to acquire Unique API token from Zitadel',
        }),
      );
    });

    it('throws error when expires_in is invalid', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(200, {
          access_token: 'token-abc',
          expires_in: -1,
        }),
      );

      const auth = createExternalAuth();

      await expect(auth.getToken()).rejects.toThrow(
        'Invalid token response: expires_in must be a positive number',
      );
    });

    it('throws error when access_token is missing from response', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(200, {
          expires_in: 3600,
        }),
      );

      const auth = createExternalAuth();

      await expect(auth.getToken()).rejects.toThrow('Invalid token response: missing access_token');
    });

    it('throws and logs error when dispatcher.request rejects', async () => {
      dispatcher.request.mockRejectedValue(new Error('network timeout'));

      const auth = createExternalAuth();

      await expect(auth.getToken()).rejects.toThrow('network timeout');
      expect(logger.error).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: 'Failed to acquire Unique API token from Zitadel',
        }),
      );
    });

    it('returns Bearer token header from getAuthHeaders()', async () => {
      dispatcher.request.mockResolvedValue(
        createDispatcherResponse(200, {
          access_token: 'token-xyz',
          expires_in: 3600,
        }),
      );

      const auth = createExternalAuth();
      const headers = await auth.getAuthHeaders();

      expect(headers).toStrictEqual({
        Authorization: 'Bearer token-xyz',
      });
    });
  });
});
