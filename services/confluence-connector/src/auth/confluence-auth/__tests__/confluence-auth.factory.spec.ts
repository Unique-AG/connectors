import { createMock } from '@golevelup/ts-vitest';
import { describe, expect, it, vi } from 'vitest';
import { AuthMode, type ConfluenceConfig } from '../../../config';
import type { TenantConfig } from '../../../config/tenant-config-loader';
import type { ProxyService } from '../../../proxy';
import type { TenantContext } from '../../../tenant/tenant-context.interface';
import { tenantStorage } from '../../../tenant/tenant-context.storage';
import { Redacted } from '../../../utils/redacted';
import { ConfluenceAuthFactory } from '../confluence-auth.factory';
import { BasicAuthStrategy } from '../strategies/basic-auth.strategy';
import { OAuth2LoAuthStrategy } from '../strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from '../strategies/pat-auth.strategy';

vi.mock('../strategies/oauth2lo-auth.strategy', () => ({
  OAuth2LoAuthStrategy: vi.fn().mockImplementation(() => ({
    getAuthorizationHeader: vi.fn().mockResolvedValue('Bearer oauth-token'),
  })),
}));

vi.mock('../strategies/pat-auth.strategy', () => ({
  PatAuthStrategy: vi.fn().mockImplementation(() => ({
    getAuthorizationHeader: vi.fn().mockResolvedValue('Bearer pat-token'),
  })),
}));

vi.mock('../strategies/basic-auth.strategy', () => ({
  BasicAuthStrategy: vi.fn().mockImplementation(() => ({
    getAuthorizationHeader: vi.fn().mockResolvedValue('Basic dXNlcjpwYXNz'),
  })),
}));

const mockProxyService = createMock<ProxyService>();

function createFactory(): ConfluenceAuthFactory {
  return new ConfluenceAuthFactory(mockProxyService);
}

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

const mockTenant: TenantContext = {
  name: 'test-tenant',
  config: {} as TenantConfig,
  status: 'active',
  isScanning: false,
};

describe('ConfluenceAuthFactory', () => {
  describe('createAuthStrategy', () => {
    it('creates auth for OAuth 2LO cloud config', async () => {
      const factory = createFactory();
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'cloud',
        cloudId: 'test-cloud-id',
        auth: {
          mode: AuthMode.OAuth2Lo,
          clientId: 'client-id',
          clientSecret: new Redacted('secret'),
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config));
      const header = await auth.getAuthorizationHeader();

      expect(header).toBe('Bearer oauth-token');
      expect(OAuth2LoAuthStrategy).toHaveBeenCalledWith(config.auth, config, expect.anything());
    });

    it('creates auth for PAT data-center config', async () => {
      const factory = createFactory();
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'data-center',
        auth: {
          mode: AuthMode.Pat,
          token: new Redacted('my-pat'),
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config));
      const header = await auth.getAuthorizationHeader();

      expect(header).toBe('Bearer pat-token');
      expect(PatAuthStrategy).toHaveBeenCalledWith(config.auth);
    });

    it('creates auth for HTTP Basic data-center config', async () => {
      const factory = createFactory();
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'data-center',
        auth: {
          mode: AuthMode.Basic,
          username: 'alice',
          password: new Redacted('s3cret'),
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config));
      const header = await auth.getAuthorizationHeader();

      expect(header).toBe('Basic dXNlcjpwYXNz');
      expect(BasicAuthStrategy).toHaveBeenCalledWith(config.auth);
    });

    it('throws for unsupported auth mode', () => {
      const factory = createFactory();
      const config = {
        ...baseFields,
        instanceType: 'cloud',
        auth: { mode: 'unknown_mode' },
      } as unknown as ConfluenceConfig;

      expect(() => tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config))).toThrow(
        'Unsupported Confluence auth mode',
      );
    });
  });
});
