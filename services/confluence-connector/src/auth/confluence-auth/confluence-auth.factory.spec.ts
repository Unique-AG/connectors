import { describe, expect, it, vi } from 'vitest';
import { AuthMode, type ConfluenceConfig } from '../../config';
import type { TenantConfig } from '../../config/tenant-config-loader';
import { ServiceRegistry } from '../../tenant/service-registry';
import type { TenantContext } from '../../tenant/tenant-context.interface';
import { tenantStorage } from '../../tenant/tenant-context.storage';
import { Redacted } from '../../utils/redacted';
import { ConfluenceAuthFactory } from './confluence-auth.factory';
import { OAuth2LoAuthStrategy } from './strategies/oauth2lo-auth.strategy';
import { PatAuthStrategy } from './strategies/pat-auth.strategy';

vi.mock('./strategies/oauth2lo-auth.strategy', () => ({
  OAuth2LoAuthStrategy: vi.fn().mockImplementation(() => ({
    acquireToken: vi.fn().mockResolvedValue('oauth-token'),
  })),
}));

vi.mock('./strategies/pat-auth.strategy', () => ({
  PatAuthStrategy: vi.fn().mockImplementation(() => ({
    acquireToken: vi.fn().mockResolvedValue('pat-token'),
  })),
}));

const mockServiceLogger = { info: vi.fn(), error: vi.fn() };
const mockServiceRegistry = {
  getServiceLogger: vi.fn().mockReturnValue(mockServiceLogger),
} as unknown as ServiceRegistry;

function createFactory(): ConfluenceAuthFactory {
  return new ConfluenceAuthFactory(mockServiceRegistry);
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
  logger: { info: vi.fn(), child: vi.fn() } as unknown as TenantContext['logger'],
  isScanning: false,
};

describe('ConfluenceAuthFactory', () => {
  describe('createAuthStrategy', () => {
    it('creates auth for OAuth 2LO cloud config', async () => {
      const factory = createFactory();
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'cloud',
        auth: {
          mode: AuthMode.OAUTH_2LO,
          clientId: 'client-id',
          clientSecret: new Redacted('secret'),
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config));
      const token = await auth.acquireToken();

      expect(token).toBe('oauth-token');
      expect(OAuth2LoAuthStrategy).toHaveBeenCalledWith(config.auth, config, mockServiceRegistry);
    });

    it('creates auth for PAT data-center config', async () => {
      const factory = createFactory();
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'data-center',
        auth: {
          mode: AuthMode.PAT,
          token: new Redacted('my-pat'),
        },
      };

      const auth = tenantStorage.run(mockTenant, () => factory.createAuthStrategy(config));
      const token = await auth.acquireToken();

      expect(token).toBe('pat-token');
      expect(PatAuthStrategy).toHaveBeenCalledWith(config.auth);
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

    it('throws when called outside tenant context due to logger lookup', () => {
      const factory = new ConfluenceAuthFactory(new ServiceRegistry());
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'cloud',
        auth: {
          mode: AuthMode.OAUTH_2LO,
          clientId: 'client-id',
          clientSecret: new Redacted('secret'),
        },
      };

      expect(() => factory.createAuthStrategy(config)).toThrow(
        'No tenant context — called outside of sync execution',
      );
    });
  });
});
