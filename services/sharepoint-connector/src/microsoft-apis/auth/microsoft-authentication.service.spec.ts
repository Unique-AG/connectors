import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../../utils/redacted';
import { MicrosoftAuthenticationService } from './microsoft-authentication.service';
import { ClientSecretAuthStrategy } from './strategies/client-secret-auth.strategy';
import { AuthenticationScope } from './types';

vi.mock('@azure/msal-node', () => ({
  ConfidentialClientApplication: vi.fn().mockImplementation(() => ({
    acquireTokenByClientCredential: vi.fn(),
  })),
}));

describe('MicrosoftAuthenticationService', () => {
  let mockConfigService: {
    get: ReturnType<typeof vi.fn>;
  };
  let mockProxyService: {
    getDispatcher: ReturnType<typeof vi.fn>;
  };
  let mockDispatcher: unknown;

  beforeEach(async () => {
    mockConfigService = {
      get: vi.fn(),
    };
    mockDispatcher = {};
    mockProxyService = {
      getDispatcher: vi.fn().mockReturnValue(mockDispatcher),
    };
  });

  it('uses ClientSecretAuthStrategy when corresponding mode is selected', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.auth.mode') return 'client-secret';
      if (key === 'sharepoint') {
        return {
          tenantId: 'tenant-123',
          auth: {
            mode: 'client-secret',
            clientId: 'client-456',
            clientSecret: new Redacted('secret-789'),
          },
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(
      mockConfigService as never,
      mockProxyService as never,
    );

    expect(service).toBeDefined();
    expect(mockProxyService.getDispatcher).toHaveBeenCalledWith('always');
    // biome-ignore lint/suspicious/noExplicitAny: Access private property for testing
    expect((service as any).strategy).toBeInstanceOf(ClientSecretAuthStrategy);
  });

  it('delegates getAccessToken to the selected strategy', async () => {
    const mockStrategy = {
      acquireNewToken: vi.fn().mockResolvedValue({
        token: 'test-token-123',
        expiresAt: Date.now() + 3600000,
      }),
    };

    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.auth.mode') return 'client-secret';
      if (key === 'sharepoint') {
        return {
          tenantId: 'tenant-123',
          auth: {
            mode: 'client-secret',
            clientId: 'client-456',
            clientSecret: new Redacted('secret-789'),
          },
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(
      mockConfigService as never,
      mockProxyService as never,
    );
    // biome-ignore lint/suspicious/noExplicitAny: Override private property for testing
    (service as any).strategy = mockStrategy;

    const token = await service.getAccessToken(AuthenticationScope.GRAPH);

    expect(token).toBe('test-token-123');
    expect(mockStrategy.acquireNewToken).toHaveBeenCalledTimes(1);
  });
});
