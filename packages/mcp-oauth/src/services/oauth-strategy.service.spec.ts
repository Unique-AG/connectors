import { TestBed } from '@suites/unit';
import passport from 'passport';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { OAuthStrategyService, STRATEGY_NAME } from './oauth-strategy.service';

vi.mock('passport');

describe('OAuthStrategyService', () => {
  let service: OAuthStrategyService;
  let options: McpOAuthModuleOptions;
  // biome-ignore lint/suspicious/noExplicitAny: Strategies are unfortunately not typed yet.
  let mockStrategy: any;

  beforeEach(async () => {
    mockStrategy = vi.fn();

    options = {
      hmacSecret: 'test-secret',
      authCodeExpiresIn: 600,
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      oauthSessionExpiresIn: 600000,
      serverUrl: 'http://localhost:3000',
      resource: 'http://localhost:3000/mcp',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      jwtSigningAlgorithm: 'HS256',
      idTokenExpiresIn: 3600,
      protectedResourceMetadata: {
        scopesSupported: ['offline_access'],
        bearerMethodsSupported: ['header'],
        mcpVersionsSupported: ['2025-06-18'],
      },
      authorizationServerMetadata: {
        responseTypesSupported: ['code'],
        responseModesSupported: ['query'],
        grantTypesSupported: ['authorization_code', 'refresh_token'],
        tokenEndpointAuthMethodsSupported: ['client_secret_basic', 'client_secret_post', 'none'],
        scopesSupported: ['offline_access'],
        codeChallengeMethodsSupported: ['plain', 'S256'],
        idTokenSigningAlgValuesSupported: ['HS256'],
        subjectTypesSupported: ['public'],
      },
      encryptionService: vi.fn(),
      oauthStore: vi.fn(),
      metricService: vi.fn(),
      provider: {
        name: 'TestProvider',
        strategy: mockStrategy,
        strategyOptions: vi.fn().mockReturnValue({
          clientID: 'test-client',
          clientSecret: 'test-secret',
          callbackURL: 'http://localhost:3000/oauth/callback',
        }),
        profileMapper: vi.fn().mockImplementation((profile) => ({
          id: profile.id,
          username: profile.username,
          displayName: profile.displayName,
          emails: profile.emails,
        })),
      },
    };

    const { unit } = await TestBed.solitary(OAuthStrategyService)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl((stubFn) => ({ ...stubFn(), ...options }))
      .compile();

    service = unit;
  });

  describe('onModuleInit', () => {
    it('registers OAuth strategy with passport on initialization', () => {
      service.onModuleInit();

      expect(options.provider.strategyOptions).toHaveBeenCalledWith({
        serverUrl: 'http://localhost:3000',
        clientId: 'test-client',
        clientSecret: 'test-secret',
        callbackPath: '/auth/callback',
      });
      expect(mockStrategy).toHaveBeenCalled();
      expect(passport.use).toHaveBeenCalledWith(STRATEGY_NAME, expect.any(Object));
    });

    it('configures strategy with profile mapping callback', () => {
      service.onModuleInit();

      const strategyCallback = mockStrategy.mock.calls[0][1];
      const mockProfile = {
        id: 'user-123',
        username: 'testuser',
        displayName: 'Test User',
        emails: [{ value: 'test@example.com' }],
      };

      const done = vi.fn();
      strategyCallback('access-token', 'refresh-token', mockProfile, done);

      expect(options.provider.profileMapper).toHaveBeenCalledWith(mockProfile);
      expect(done).toHaveBeenCalledWith(null, {
        profile: {
          id: 'user-123',
          username: 'testuser',
          displayName: 'Test User',
          emails: [{ value: 'test@example.com' }],
        },
        accessToken: 'access-token',
        refreshToken: 'refresh-token',
        provider: 'TestProvider',
      });
    });

    it('handles profile mapping errors gracefully', () => {
      service.onModuleInit();

      const strategyCallback = mockStrategy.mock.calls[0][1];
      const error = new Error('Profile mapping failed');
      options.provider.profileMapper = vi.fn().mockImplementation(() => {
        throw error;
      });

      const done = vi.fn();
      strategyCallback('access-token', 'refresh-token', {}, done);

      expect(done).toHaveBeenCalledWith(error, null);
    });
  });

  describe('getStrategyName', () => {
    it('provides consistent strategy name for passport authentication', () => {
      const name = service.getStrategyName();

      expect(name).toBe(STRATEGY_NAME);
      expect(name).toBe('oauth-provider');
    });
  });
});
