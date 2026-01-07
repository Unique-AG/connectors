import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../../utils/redacted';
import { MicrosoftAuthenticationService } from './microsoft-authentication.service';
import { ClientSecretAuthStrategy } from './strategies/client-secret-auth.strategy';
import { OidcAuthStrategy } from './strategies/oidc-auth.strategy';
import { AuthenticationScope } from './types';

vi.mock('@azure/msal-node', () => ({
  ConfidentialClientApplication: vi.fn().mockImplementation(() => ({
    acquireTokenByClientCredential: vi.fn(),
  })),
}));

vi.mock('@azure/identity', () => ({
  DefaultAzureCredential: vi.fn().mockImplementation(() => ({
    getToken: vi.fn(),
  })),
}));

describe('MicrosoftAuthenticationService', () => {
  let mockConfigService: {
    get: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    mockConfigService = {
      get: vi.fn(),
    };
  });

  it('uses ClientSecretAuthStrategy when corresponding mode is selected', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.auth.mode') return 'client-secret';
      if (key === 'sharepoint') {
        return {
          auth: {
            mode: 'client-secret',
            tenantId: 'tenant-123',
            clientId: 'client-456',
            clientSecret: new Redacted('secret-789'),
          },
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(mockConfigService as never);

    expect(service).toBeDefined();
    // biome-ignore lint/suspicious/noExplicitAny: Access private property for testing
    expect((service as any).strategy).toBeInstanceOf(ClientSecretAuthStrategy);
  });

  it('uses OidcAuthStrategy when corresponding mode is selected', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.auth.mode') return 'oidc';
      if (key === 'sharepoint') {
        return {
          auth: {
            mode: 'oidc',
            tenantId: 'tenant-123',
          },
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(mockConfigService as never);

    expect(service).toBeDefined();
    // biome-ignore lint/suspicious/noExplicitAny: Access private property for testing
    expect((service as any).strategy).toBeInstanceOf(OidcAuthStrategy);
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
          auth: {
            mode: 'client-secret',
            tenantId: 'tenant-123',
            clientId: 'client-456',
            clientSecret: new Redacted('secret-789'),
          },
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(mockConfigService as never);
    // biome-ignore lint/suspicious/noExplicitAny: Override private property for testing
    (service as any).strategy = mockStrategy;

    const token = await service.getAccessToken(AuthenticationScope.GRAPH);

    expect(token).toBe('test-token-123');
    expect(mockStrategy.acquireNewToken).toHaveBeenCalledTimes(1);
  });
});
