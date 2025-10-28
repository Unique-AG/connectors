import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Redacted } from '../../utils/redacted';
import { ClientSecretAuthStrategy } from './client-secret-auth.strategy';
import { MicrosoftAuthenticationService } from './microsoft-authentication.service';
import { OidcAuthStrategy } from './oidc-auth.strategy';

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

  it('uses ClientSecretAuthStrategy when useOidc is false', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.authMode') return 'client-secret';
      if (key === 'sharepoint') {
        return {
          authMode: 'client-secret',
          authTenantId: 'tenant-123',
          authClientId: 'client-456',
          authClientSecret: new Redacted('secret-789'),
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(mockConfigService as never);

    expect(service).toBeDefined();
    // biome-ignore lint/suspicious/noExplicitAny: Access private property for testing
    expect((service as any).strategy).toBeInstanceOf(ClientSecretAuthStrategy);
  });

  it('uses OidcAuthStrategy when useOidc is true', () => {
    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.authMode') return 'oidc';
      if (key === 'sharepoint') {
        return {
          authMode: 'oidc',
          authTenantId: 'tenant-123',
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
      getAccessToken: vi.fn().mockResolvedValue('mock-token'),
    };

    mockConfigService.get.mockImplementation((key: string) => {
      if (key === 'sharepoint.authMode') return 'client-secret';
      if (key === 'sharepoint') {
        return {
          authMode: 'client-secret',
          authTenantId: 'tenant-123',
          authClientId: 'client-456',
          authClientSecret: new Redacted('secret-789'),
        };
      }
      return undefined;
    });

    const service = new MicrosoftAuthenticationService(mockConfigService as never);
    // biome-ignore lint/suspicious/noExplicitAny: Override private property for testing
    (service as any).strategy = mockStrategy;

    const token = await service.getAccessToken();

    expect(token).toBe('mock-token');
    expect(mockStrategy.getAccessToken).toHaveBeenCalledTimes(1);
  });
});
