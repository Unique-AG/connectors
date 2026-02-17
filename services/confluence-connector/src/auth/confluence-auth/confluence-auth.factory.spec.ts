import { describe, expect, it, vi } from 'vitest';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { Redacted } from '../../utils/redacted';
import { ConfluenceAuthFactory } from './confluence-auth.factory';

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

const baseFields = {
  baseUrl: 'https://confluence.example.com',
  apiRateLimitPerMinute: 100,
  ingestSingleLabel: 'sync',
  ingestAllLabel: 'sync-all',
};

describe('ConfluenceAuthFactory', () => {
  const factory = new ConfluenceAuthFactory();

  describe('create', () => {
    it('creates auth for OAuth 2LO cloud config', async () => {
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'cloud',
        auth: {
          mode: AuthMode.OAUTH_2LO,
          clientId: 'client-id',
          clientSecret: new Redacted('secret'),
        },
      };

      const auth = factory.createAuthStrategy(config);
      const token = await auth.acquireToken();

      expect(token).toBe('oauth-token');
    });

    it('creates auth for PAT data-center config', async () => {
      const config: ConfluenceConfig = {
        ...baseFields,
        instanceType: 'data-center',
        auth: {
          mode: AuthMode.PAT,
          token: new Redacted('my-pat'),
        },
      };

      const auth = factory.createAuthStrategy(config);
      const token = await auth.acquireToken();

      expect(token).toBe('pat-token');
    });

    it('throws for unsupported auth mode', () => {
      const config = {
        ...baseFields,
        instanceType: 'cloud',
        auth: { mode: 'unknown_mode' },
      } as unknown as ConfluenceConfig;

      expect(() => factory.createAuthStrategy(config)).toThrow('Unsupported Confluence auth mode');
    });
  });
});
