import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueAuthMode } from '../../../config';
import { ServiceRegistry } from '../../../tenant/service-registry';
import type { TenantContext } from '../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../tenant/tenant-context.storage';
import { Redacted } from '../../../utils/redacted';
import { UniqueAuth } from '../unique-auth.abstract';
import { ZitadelAuthStrategy } from './zitadel-auth.strategy';

const { mockRequest } = vi.hoisted(() => ({
  mockRequest: vi.fn(),
}));

vi.mock('undici', () => {
  return {
    request: mockRequest,
  };
});

function createExternalConfig() {
  return {
    serviceAuthMode: UniqueAuthMode.EXTERNAL,
    zitadelOauthTokenUrl: 'https://zitadel.example.com/oauth/v2/token',
    zitadelProjectId: new Redacted('project-id-123'),
    zitadelClientId: 'client-id',
    zitadelClientSecret: new Redacted('client-secret'),
    ingestionServiceBaseUrl: 'https://ingestion.example.com',
    scopeManagementServiceBaseUrl: 'https://scope.example.com',
    apiRateLimitPerMinute: 100,
  };
}

function mockSuccessfulTokenResponse(token = 'access-token-xyz', expiresIn = 3600) {
  mockRequest.mockResolvedValue({
    statusCode: 200,
    body: {
      json: vi.fn().mockResolvedValue({
        access_token: token,
        expires_in: expiresIn,
        token_type: 'Bearer',
      }),
    },
  });
}

describe('ZitadelAuthStrategy', () => {
  let loggerErrorMock: ReturnType<typeof vi.fn>;
  let mockServiceRegistry: ServiceRegistry;
  const mockTenant: TenantContext = {
    name: 'test-tenant',
    config: {} as TenantContext['config'],
    isScanning: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();

    loggerErrorMock = vi.fn();
    mockServiceRegistry = {
      getServiceLogger: vi.fn().mockReturnValue({
        error: loggerErrorMock,
      }),
    } as unknown as ServiceRegistry;
  });

  it('extends UniqueServiceAuth', () => {
    const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

    expect(strategy).toBeInstanceOf(UniqueAuth);
  });

  describe('getHeaders', () => {
    it('returns Authorization header with Bearer token', async () => {
      mockSuccessfulTokenResponse('my-token');
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      const headers = await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      expect(headers).toEqual({ Authorization: 'Bearer my-token' });
    });

    it('sends Basic auth header with base64-encoded credentials', async () => {
      mockSuccessfulTokenResponse();
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      const expectedBasicAuth = Buffer.from('client-id:client-secret').toString('base64');
      expect(mockRequest).toHaveBeenCalledWith(
        'https://zitadel.example.com/oauth/v2/token',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: `Basic ${expectedBasicAuth}`,
          }),
        }),
      );
    });

    it('sends correct Content-Type header', async () => {
      mockSuccessfulTokenResponse();
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      expect(mockRequest).toHaveBeenCalledWith(
        'https://zitadel.example.com/oauth/v2/token',
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/x-www-form-urlencoded',
          }),
        }),
      );
    });

    it('sends scope with project ID and grant_type in body', async () => {
      mockSuccessfulTokenResponse();
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      const requestOptions = mockRequest.mock.calls[0]?.[1] as { body: string };
      const params = new URLSearchParams(requestOptions.body);
      expect(params.get('grant_type')).toBe('client_credentials');
      expect(params.get('scope')).toContain('project-id-123');
      expect(params.get('scope')).toContain('openid profile email');
    });

    it('sends POST request to the configured token URL', async () => {
      mockSuccessfulTokenResponse();
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      expect(mockRequest).toHaveBeenCalledWith(
        'https://zitadel.example.com/oauth/v2/token',
        expect.objectContaining({
          method: 'POST',
        }),
      );
    });

    it('caches the token across sequential calls', async () => {
      mockSuccessfulTokenResponse('cached-token', 3600);
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await tenantStorage.run(mockTenant, () => strategy.getHeaders());
      await tenantStorage.run(mockTenant, () => strategy.getHeaders());

      expect(mockRequest).toHaveBeenCalledTimes(1);
    });

    it('deduplicates concurrent getHeaders calls into a single request', async () => {
      mockSuccessfulTokenResponse('deduped-token', 3600);
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      const [headersA, headersB] = await Promise.all([
        tenantStorage.run(mockTenant, () => strategy.getHeaders()),
        tenantStorage.run(mockTenant, () => strategy.getHeaders()),
      ]);

      expect(mockRequest).toHaveBeenCalledTimes(1);
      expect(headersA).toEqual({ Authorization: 'Bearer deduped-token' });
      expect(headersB).toEqual({ Authorization: 'Bearer deduped-token' });
    });

    it('throws when response status is not 2xx', async () => {
      mockRequest.mockResolvedValue({
        statusCode: 401,
        body: {
          text: vi.fn().mockResolvedValue('Unauthorized'),
        },
      });
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await expect(tenantStorage.run(mockTenant, () => strategy.getHeaders())).rejects.toThrow(
        'Error response from https://zitadel.example.com/oauth/v2/token: 401 Unauthorized',
      );
    });

    it('throws when access_token is missing in response', async () => {
      mockRequest.mockResolvedValue({
        statusCode: 200,
        body: {
          json: vi.fn().mockResolvedValue({
            expires_in: 3600,
            token_type: 'Bearer',
          }),
        },
      });
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await expect(tenantStorage.run(mockTenant, () => strategy.getHeaders())).rejects.toThrow(
        'Invalid token response: missing access_token',
      );
    });

    it('logs error via sanitizeError before rethrowing', async () => {
      mockRequest.mockRejectedValue(new Error('network failure'));
      const strategy = new ZitadelAuthStrategy(createExternalConfig(), mockServiceRegistry);

      await expect(tenantStorage.run(mockTenant, () => strategy.getHeaders())).rejects.toThrow(
        'network failure',
      );

      expect(loggerErrorMock).toHaveBeenCalledOnce();
      // biome-ignore lint/style/noNonNullAssertion: Asserted above with toHaveBeenCalledOnce
      const loggedPayload = loggerErrorMock.mock.calls[0]![0];
      expect(loggedPayload.msg).toBe('Failed to acquire Unique API token from Zitadel');
      expect(loggedPayload.error).toBeTypeOf('object');
      expect(loggedPayload.error).toHaveProperty('message', 'network failure');
    });
  });
});
