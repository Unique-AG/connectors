import { randomBytes } from 'node:crypto';
import { BadRequestException, UnauthorizedException } from '@nestjs/common';
import { type Mocked, TestBed } from '@suites/unit';
import { type NextFunction, type Request, type Response } from 'express';
import passport from 'passport';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { ClientService } from '../services/client.service';
import { McpOAuthService } from '../services/mcp-oauth.service';
import { MetricService } from '../services/metric.service';
import { type PassportUser, STRATEGY_NAME } from '../services/oauth-strategy.service';
import { OAuthController } from './oauth.controller';

vi.mock('passport');
vi.mock('node:crypto', async () => {
  const actual = await vi.importActual<typeof import('node:crypto')>('node:crypto');
  return {
    ...actual,
    randomBytes: vi.fn(() => ({
      toString: (_encoding: string) => 'mock-random-string',
    })),
  };
});

describe('OAuthController', () => {
  let controller: OAuthController;
  let authService: Mocked<McpOAuthService>;
  let clientService: Mocked<ClientService>;
  let store: Mocked<IOAuthStore>;
  let metricService: MetricService;
  let mockOptions: McpOAuthModuleOptions;
  let mockRequest: Partial<Request>;
  let mockResponse: Partial<Response>;
  let mockNext: NextFunction;

  beforeEach(async () => {
    mockOptions = {
      hmacSecret: 'test-hmac-secret',
      authCodeExpiresIn: 600,
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      oauthSessionExpiresIn: 600000,
      serverUrl: 'https://auth.example.com',
      resource: 'https://mcp.example.com',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      jwtSigningAlgorithm: 'HS256',
      idTokenExpiresIn: 3600,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      protectedResourceMetadata: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      authorizationServerMetadata: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      encryptionService: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      oauthStore: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      metricService: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      provider: {} as any,
    };

    mockRequest = {
      query: {},
      user: undefined,
    };

    mockResponse = {
      redirect: vi.fn(),
      status: vi.fn().mockReturnThis(),
      json: vi.fn().mockReturnThis(),
    };

    mockNext = vi.fn();

    const { unit, unitRef } = await TestBed.solitary(OAuthController)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl((stubFn) => ({ ...stubFn(), ...mockOptions }))
      .compile();

    controller = unit;
    authService = unitRef.get(McpOAuthService);
    clientService = unitRef.get(ClientService);
    store = unitRef.get(OAUTH_STORE_TOKEN);
    metricService = unitRef.get(MetricService);
  });

  describe('authorize', () => {
    const mockClient = {
      client_id: 'test-client-id',
      client_name: 'Test Client',
      redirect_uris: ['http://localhost:3000/callback'],
      grant_types: ['authorization_code'],
      response_types: ['code'],
      token_endpoint_auth_method: 'none',
      created_at: new Date(),
      updated_at: new Date(),
    };

    beforeEach(() => {
      clientService.getClient.mockResolvedValue(mockClient);
      clientService.validateRedirectUri.mockResolvedValue(true);
      store.storeOAuthSession.mockResolvedValue(undefined);
      vi.spyOn(passport, 'authenticate').mockReturnValue(vi.fn());
    });

    describe('successful authorization', () => {
      it('initiates OAuth flow with valid parameters', async () => {
        await controller.authorize(
          'code',
          'test-client-id',
          'http://localhost:3000/callback',
          'challenge-123',
          'S256',
          'client-state-456',
          'offline_access',
          'https://mcp.example.com',
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(metricService.incrementFlowsStarted).toHaveBeenCalled();
        expect(clientService.getClient).toHaveBeenCalledWith('test-client-id');
        expect(clientService.validateRedirectUri).toHaveBeenCalledWith(
          'test-client-id',
          'http://localhost:3000/callback',
        );
        expect(store.storeOAuthSession).toHaveBeenCalled();
        expect(passport.authenticate).toHaveBeenCalledWith(STRATEGY_NAME, expect.any(Object));
      });

      it('stores OAuth session with correct parameters', async () => {
        await controller.authorize(
          'code',
          'test-client-id',
          'http://localhost:3000/callback',
          'challenge-123',
          'S256',
          'client-state-456',
          'offline_access',
          'https://mcp.example.com',
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(store.storeOAuthSession).toHaveBeenCalledWith(
          'mock-random-string',
          expect.objectContaining({
            sessionId: 'mock-random-string',
            clientId: 'test-client-id',
            redirectUri: 'http://localhost:3000/callback',
            codeChallenge: 'challenge-123',
            codeChallengeMethod: 'S256',
            oauthState: 'client-state-456',
            scope: 'offline_access',
            resource: 'https://mcp.example.com',
          }),
        );
      });

      it('generates HMAC for session security', async () => {
        const actualRandomBytes = (
          await vi.importActual<typeof import('node:crypto')>('node:crypto')
        ).randomBytes;

        vi.mocked(randomBytes).mockImplementation((size: number) => {
          if (size === 32) {
            return {
              toString: (encoding: string) =>
                encoding === 'base64url' ? `random-${size}` : `random-${size}`,
              // biome-ignore lint/suspicious/noExplicitAny: Mock implementation
            } as any;
          }
          return actualRandomBytes(size);
        });

        await controller.authorize(
          'code',
          'test-client-id',
          'http://localhost:3000/callback',
          'challenge-123',
          'S256',
          'client-state-456',
          'offline_access',
          'https://mcp.example.com',
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        const sessionCall = (store.storeOAuthSession as ReturnType<typeof vi.fn>).mock
          .calls[0]?.[1];
        expect(sessionCall.state).toBeDefined();
        expect(sessionCall.state).toMatch(/^[A-Za-z0-9_-]+$/); // Base64url format
      });
    });

    describe('validation errors', () => {
      it('throws error for invalid response type', async () => {
        await expect(
          controller.authorize(
            'token', // Invalid for OAuth 2.1
            'test-client-id',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow(BadRequestException);

        await expect(
          controller.authorize(
            'token',
            'test-client-id',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow('Invalid response type');
      });

      it('throws error for missing client_id', async () => {
        await expect(
          controller.authorize(
            'code',
            '',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow(BadRequestException);

        await expect(
          controller.authorize(
            'code',
            '',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow('Missing client_id parameter');
      });

      it('throws error for invalid resource parameter', async () => {
        await expect(
          controller.authorize(
            'code',
            'test-client-id',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://wrong-resource.com', // Different from configured resource
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow(BadRequestException);

        await expect(
          controller.authorize(
            'code',
            'test-client-id',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://wrong-resource.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow('Invalid resource parameter');
      });

      it('throws error for non-existent client', async () => {
        clientService.getClient.mockResolvedValue(null);

        await expect(
          controller.authorize(
            'code',
            'non-existent-client',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow(BadRequestException);

        await expect(
          controller.authorize(
            'code',
            'non-existent-client',
            'http://localhost:3000/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow('Invalid client_id parameter');
      });

      it('throws error for invalid redirect URI', async () => {
        clientService.validateRedirectUri.mockResolvedValue(false);

        await expect(
          controller.authorize(
            'code',
            'test-client-id',
            'http://evil.com/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow(BadRequestException);

        await expect(
          controller.authorize(
            'code',
            'test-client-id',
            'http://evil.com/callback',
            'challenge-123',
            'S256',
            'state-456',
            'offline_access',
            'https://mcp.example.com',
            mockRequest as Request,
            mockResponse as Response,
            mockNext,
          ),
        ).rejects.toThrow('Invalid redirect_uri parameter');
      });
    });
  });

  describe('callback', () => {
    const mockUser: PassportUser = {
      profile: {
        id: 'user-123',
        username: 'testuser',
        displayName: 'Test User',
        email: 'test@example.com',
      },
      accessToken: 'provider-access-token',
      refreshToken: 'provider-refresh-token',
      provider: 'TestProvider',
    };

    const mockState = Buffer.from(
      JSON.stringify({
        sessionId: 'session-123',
        sessionNonce: 'nonce-456',
        sessionHmac: 'hmac-789',
      }),
    ).toString('base64url');

    beforeEach(() => {
      vi.spyOn(passport, 'authenticate').mockImplementation((_strategy, _options, callback) => {
        return (_req: Request, _res: Response, _next: NextFunction) => {
          if (callback) {
            // Simulate successful authentication
            callback(null, mockUser, undefined);
          }
        };
        // biome-ignore lint/suspicious/noExplicitAny: Mock implementation
      }) as any;
    });

    describe('successful callback', () => {
      it('processes successful authentication', async () => {
        const redirectUrl = 'http://localhost:3000/callback?code=auth-code&state=client-state';
        authService.processAuthenticationSuccess.mockResolvedValue({ redirectUrl });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(authService.processAuthenticationSuccess).toHaveBeenCalledWith({
          user: mockUser,
          sessionId: 'session-123',
          sessionNonce: 'nonce-456',
          sessionHmac: 'hmac-789',
        });
        expect(mockResponse.redirect).toHaveBeenCalledWith(redirectUrl);
      });

      it('sets user on request object', async () => {
        authService.processAuthenticationSuccess.mockResolvedValue({
          redirectUrl: 'http://localhost:3000/callback?code=auth-code',
        });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(mockRequest.user).toEqual(mockUser);
      });
    });

    describe('authentication failures', () => {
      it('handles authentication error from strategy', async () => {
        const authError = new Error('OAuth provider error');
        vi.spyOn(passport, 'authenticate').mockImplementation((_strategy, _options, callback) => {
          return (_req: Request, _res: Response, _next: NextFunction) => {
            if (callback) {
              callback(authError, null, undefined);
            }
          };
          // biome-ignore lint/suspicious/noExplicitAny: Mock implementation
        }) as any;

        authService.processAuthenticationError.mockResolvedValue({
          redirectUrl: 'http://localhost:3000/callback?error=server_error',
          errorMessage: 'OAuth provider error',
        });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(authService.processAuthenticationError).toHaveBeenCalledWith({
          error: expect.any(UnauthorizedException),
          state: mockState,
        });
        expect(mockResponse.redirect).toHaveBeenCalledWith(
          'http://localhost:3000/callback?error=server_error',
        );
      });

      it('handles missing user from strategy', async () => {
        vi.spyOn(passport, 'authenticate').mockImplementation((_strategy, _options, callback) => {
          return (_req: Request, _res: Response, _next: NextFunction) => {
            if (callback) {
              callback(null, null, { message: 'User denied access' });
            }
          };
          // biome-ignore lint/suspicious/noExplicitAny: Mock implementation
        }) as any;

        authService.processAuthenticationError.mockResolvedValue({
          redirectUrl: 'http://localhost:3000/callback?error=access_denied',
          errorMessage: 'User denied access',
        });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(mockResponse.redirect).toHaveBeenCalledWith(
          'http://localhost:3000/callback?error=access_denied',
        );
      });

      it('handles missing state parameter', async () => {
        authService.processAuthenticationError.mockResolvedValue({
          redirectUrl: null,
          errorMessage: 'Authentication failed',
        });

        await controller.callback('', mockRequest as Request, mockResponse as Response, mockNext);

        expect(mockResponse.status).toHaveBeenCalledWith(401);
        expect(mockResponse.json).toHaveBeenCalledWith({
          error: 'Authentication failed',
          error_description: 'Authentication failed',
        });
      });
    });

    describe('error recovery', () => {
      it('falls back to JSON response when redirect URL is not available', async () => {
        vi.spyOn(passport, 'authenticate').mockImplementation((_strategy, _options, callback) => {
          return (_req: Request, _res: Response, _next: NextFunction) => {
            if (callback) {
              callback(new Error('Critical error'), null, undefined);
            }
          };
          // biome-ignore lint/suspicious/noExplicitAny: Mock implementation
        }) as any;

        authService.processAuthenticationError.mockResolvedValue({
          redirectUrl: null,
          errorMessage: 'Critical error occurred',
        });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(mockResponse.status).toHaveBeenCalledWith(401);
        expect(mockResponse.json).toHaveBeenCalledWith({
          error: 'Authentication failed',
          error_description: 'Critical error occurred',
        });
      });
    });
  });
});
