import { describe, expect, it, vi } from 'vitest';
import { AuthMode, type ConfluenceConfig } from '../../config';
import { Redacted } from '../../utils/redacted';
import { ConfluenceAuthFactory } from './confluence-auth.factory';

vi.mock('./strategies/oauth2lo-auth.strategy', () => ({
  OAuth2LoAuthStrategy: vi.fn().mockImplementation(() => ({
    acquireToken: vi.fn().mockResolvedValue({
      accessToken: 'oauth-token',
      expiresAt: new Date(Date.now() + 3600_000),
    }),
  })),
}));

vi.mock('./strategies/pat-auth.strategy', () => ({
  PatAuthStrategy: vi.fn().mockImplementation(() => ({
    acquireToken: vi.fn().mockResolvedValue({
      accessToken: 'pat-token',
    }),
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

      const auth = factory.create(config);
      const token = await auth.getAccessToken();

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

      const auth = factory.create(config);
      const token = await auth.getAccessToken();

      expect(token).toBe('pat-token');
    });
  });
});
