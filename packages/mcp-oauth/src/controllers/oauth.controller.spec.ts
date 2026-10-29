import { BadRequestException, ForbiddenException, UnauthorizedException } from '@nestjs/common';
import { type Mocked, TestBed } from '@suites/unit';
import { type NextFunction, type Request, type Response } from 'express';
import passport from 'passport';
import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import type { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { ClientService } from '../services/client.service';
import { FlowBindingService } from '../services/flow-binding.service';
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

const mockCookie = {
  name: 'mcp_oauth_flow_0123456789abcdef',
  value: 'binding.signature',
  options: { httpOnly: true, secure: true, sameSite: 'lax' as const, path: '/' },
};

describe('OAuthController', () => {
  let controller: OAuthController;
  let authService: Mocked<McpOAuthService>;
  let clientService: Mocked<ClientService>;
  let store: Mocked<IOAuthStore>;
  let metricService: MetricService;
  let flowBinding: Mocked<FlowBindingService>;
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
      protectedResourceMetadata: {
        scopesSupported: ['offline_access'],
        bearerMethodsSupported: ['header'],
        mcpVersionsSupported: ['2025-06-18'],
        resourceName: 'Test MCP',
      },
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
      cookie: vi.fn().mockReturnThis(),
      clearCookie: vi.fn().mockReturnThis(),
      set: vi.fn().mockReturnThis(),
      send: vi.fn().mockReturnThis(),
    };

    mockNext = vi.fn();

    const { unit, unitRef } = await TestBed.solitary(OAuthController)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl(() => ({ ...mockOptions }))
      .compile();

    controller = unit;
    authService = unitRef.get(McpOAuthService);
    clientService = unitRef.get(ClientService);
    store = unitRef.get(OAUTH_STORE_TOKEN);
    metricService = unitRef.get(MetricService);
    flowBinding = unitRef.get(FlowBindingService);
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

    const validParams = {
      responseType: 'code',
      clientId: 'test-client-id',
      redirectUri: 'http://localhost:3000/callback',
      codeChallenge: 'challenge-123',
      codeChallengeMethod: 'S256',
      state: 'client-state-456',
      scope: 'offline_access',
      resource: 'https://mcp.example.com',
    };

    const callAuthorize = (overrides: Partial<typeof validParams> = {}) => {
      const params = { ...validParams, ...overrides };
      return controller.authorize(
        params.responseType,
        params.clientId,
        params.redirectUri,
        params.codeChallenge,
        params.codeChallengeMethod,
        params.state,
        params.scope,
        params.resource,
        mockResponse as Response,
      );
    };

    beforeEach(() => {
      clientService.getClient.mockResolvedValue(mockClient);
      clientService.validateRedirectUri.mockResolvedValue(true);
      store.storeOAuthSession.mockResolvedValue(undefined);
      flowBinding.createBinding.mockReturnValue({ cookie: mockCookie, csrfToken: 'csrf-token' });
      vi.spyOn(passport, 'authenticate').mockReturnValue(vi.fn());
    });

    describe('successful authorization', () => {
      it('validates the client and stores the session', async () => {
        await callAuthorize();

        expect(metricService.incrementFlowsStarted).toHaveBeenCalled();
        expect(clientService.getClient).toHaveBeenCalledWith('test-client-id');
        expect(clientService.validateRedirectUri).toHaveBeenCalledWith(
          'test-client-id',
          'http://localhost:3000/callback',
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

      it('shows the consent page instead of redirecting to the provider', async () => {
        await callAuthorize();

        expect(passport.authenticate).not.toHaveBeenCalled();
        expect(mockResponse.redirect).not.toHaveBeenCalled();
        expect(mockResponse.status).toHaveBeenCalledWith(200);
        const html = vi.mocked(mockResponse.send as Mock).mock.calls[0]?.[0];
        expect(html).toContain('<strong>Test Client</strong> wants to access Test MCP');
        expect(html).toContain('<strong>localhost:3000</strong>');
        expect(html).toContain('name="csrf_token" value="csrf-token"');
        expect(html).toContain('action="https://auth.example.com/auth/consent"');
      });

      it('binds the flow to the browser with a cookie', async () => {
        await callAuthorize();

        expect(flowBinding.createBinding).toHaveBeenCalledWith('mock-random-string');
        expect(mockResponse.cookie).toHaveBeenCalledWith(
          mockCookie.name,
          mockCookie.value,
          mockCookie.options,
        );
      });

      it('sends a strict CSP and forbids framing', async () => {
        await callAuthorize();

        expect(mockResponse.set).toHaveBeenCalledWith(
          expect.objectContaining({
            'Content-Security-Policy': expect.stringContaining("frame-ancestors 'none'"),
            'X-Frame-Options': 'DENY',
          }),
        );
      });

      it('falls back to the configured resource when none is requested', async () => {
        await callAuthorize({ resource: '' });

        expect(store.storeOAuthSession).toHaveBeenCalledWith(
          'mock-random-string',
          expect.objectContaining({ resource: 'https://mcp.example.com' }),
        );
      });
    });

    describe('validation errors', () => {
      it('throws error for invalid response type', async () => {
        await expect(callAuthorize({ responseType: 'token' })).rejects.toThrow(
          new BadRequestException('Invalid response type'),
        );
      });

      it('throws error for missing client_id', async () => {
        await expect(callAuthorize({ clientId: '' })).rejects.toThrow(
          new BadRequestException('Missing client_id parameter'),
        );
      });

      it('throws error for invalid resource parameter', async () => {
        await expect(callAuthorize({ resource: 'https://wrong-resource.com' })).rejects.toThrow(
          new BadRequestException('Invalid resource parameter'),
        );
      });

      it('throws error for non-existent client', async () => {
        clientService.getClient.mockResolvedValue(null);

        await expect(callAuthorize({ clientId: 'non-existent-client' })).rejects.toThrow(
          new BadRequestException('Invalid client_id parameter'),
        );
      });

      it('throws error for invalid redirect URI', async () => {
        clientService.validateRedirectUri.mockResolvedValue(false);

        await expect(callAuthorize({ redirectUri: 'http://evil.com/callback' })).rejects.toThrow(
          new BadRequestException('Invalid redirect_uri parameter'),
        );
      });

      it('throws error for a non-S256 code challenge method', async () => {
        await expect(callAuthorize({ codeChallengeMethod: 'plain' })).rejects.toThrow(
          new BadRequestException('code_challenge_method must be S256'),
        );
      });

      it('sets no cookie when validation fails', async () => {
        await expect(callAuthorize({ codeChallenge: '' })).rejects.toThrow(BadRequestException);

        expect(store.storeOAuthSession).not.toHaveBeenCalled();
        expect(mockResponse.cookie).not.toHaveBeenCalled();
      });
    });
  });

  describe('consent', () => {
    const pendingSession = {
      sessionId: 'session-123',
      state: 'pending-state',
      clientId: 'test-client-id',
      redirectUri: 'http://localhost:3000/callback',
      codeChallenge: 'challenge-123',
      codeChallengeMethod: 'S256',
      oauthState: 'client-state-456',
      scope: 'offline_access',
      resource: 'https://mcp.example.com',
      expiresAt: Date.now() + 600000,
    };

    const callConsent = (decision: 'approve' | 'deny') =>
      controller.consent(
        { session_id: 'session-123', csrf_token: 'csrf-token', decision },
        mockRequest as Request,
        mockResponse as Response,
        mockNext,
      );

    beforeEach(() => {
      mockRequest.headers = { cookie: 'flow-cookie=value' };
      flowBinding.readBinding.mockReturnValue('cookie-value');
      flowBinding.isValidCsrfToken.mockReturnValue(true);
      flowBinding.clearedCookie.mockReturnValue({
        name: mockCookie.name,
        options: { path: '/' },
      });
      store.getOAuthSession.mockResolvedValue(pendingSession);
    });

    it('redirects to the provider with the approved state on approve', async () => {
      const providerMiddleware = vi.fn();
      vi.spyOn(passport, 'authenticate').mockReturnValue(providerMiddleware);
      authService.approveConsent.mockResolvedValue('signed-provider-state');

      await callConsent('approve');

      expect(flowBinding.readBinding).toHaveBeenCalledWith('flow-cookie=value', 'session-123');
      expect(flowBinding.isValidCsrfToken).toHaveBeenCalledWith(
        'session-123',
        'cookie-value',
        'csrf-token',
      );
      expect(authService.approveConsent).toHaveBeenCalledWith(pendingSession);
      expect(passport.authenticate).toHaveBeenCalledWith(STRATEGY_NAME, {
        state: 'signed-provider-state',
      });
      expect(providerMiddleware).toHaveBeenCalledWith(mockRequest, mockResponse, mockNext);
    });

    it('redirects to the client with access_denied on deny', async () => {
      const deniedUrl = 'http://localhost:3000/callback?error=access_denied&state=client-state-456';
      authService.denyConsent.mockResolvedValue(deniedUrl);

      await callConsent('deny');

      expect(authService.denyConsent).toHaveBeenCalledWith(pendingSession);
      expect(authService.approveConsent).not.toHaveBeenCalled();
      expect(mockResponse.clearCookie).toHaveBeenCalledWith(mockCookie.name, { path: '/' });
      expect(mockResponse.redirect).toHaveBeenCalledWith(deniedUrl);
    });

    it('rejects a browser without the flow cookie', async () => {
      flowBinding.readBinding.mockReturnValue(undefined);

      await expect(callConsent('approve')).rejects.toThrow(ForbiddenException);
      expect(store.getOAuthSession).not.toHaveBeenCalled();
      expect(authService.approveConsent).not.toHaveBeenCalled();
    });

    it('rejects an invalid CSRF token', async () => {
      flowBinding.isValidCsrfToken.mockReturnValue(false);

      await expect(callConsent('approve')).rejects.toThrow(ForbiddenException);
      expect(authService.approveConsent).not.toHaveBeenCalled();
    });

    it('rejects a deny without the flow cookie', async () => {
      flowBinding.readBinding.mockReturnValue(undefined);

      await expect(callConsent('deny')).rejects.toThrow(ForbiddenException);
      expect(authService.denyConsent).not.toHaveBeenCalled();
    });

    it('rejects an unknown session', async () => {
      store.getOAuthSession.mockResolvedValue(undefined);

      await expect(callConsent('approve')).rejects.toThrow(
        new BadRequestException('Invalid or expired OAuth session.'),
      );
    });

    it('rejects an expired session', async () => {
      store.getOAuthSession.mockResolvedValue({ ...pendingSession, expiresAt: Date.now() - 1 });

      await expect(callConsent('approve')).rejects.toThrow(BadRequestException);
      expect(authService.approveConsent).not.toHaveBeenCalled();
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
      mockRequest.headers = { cookie: 'flow-cookie=value' };
      flowBinding.readBinding.mockReturnValue('cookie-value');
      flowBinding.clearedCookie.mockReturnValue({
        name: mockCookie.name,
        options: { path: '/' },
      });
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

    describe('browser binding', () => {
      it('verifies the flow cookie of the session in the state', async () => {
        authService.processAuthenticationSuccess.mockResolvedValue({ redirectUrl: 'http://x/cb' });

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(flowBinding.readBinding).toHaveBeenCalledWith('flow-cookie=value', 'session-123');
        expect(mockResponse.clearCookie).toHaveBeenCalledWith(mockCookie.name, { path: '/' });
      });

      it('rejects a callback without the flow cookie before contacting the provider', async () => {
        flowBinding.readBinding.mockReturnValue(undefined);

        await controller.callback(
          mockState,
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(passport.authenticate).not.toHaveBeenCalled();
        expect(authService.processAuthenticationSuccess).not.toHaveBeenCalled();
        expect(mockResponse.redirect).not.toHaveBeenCalled();
        expect(mockResponse.status).toHaveBeenCalledWith(401);
        expect(mockResponse.json).toHaveBeenCalledWith({
          error: 'Authentication failed',
          error_description: 'This sign-in was not started in this browser.',
        });
      });

      it('rejects a malformed state', async () => {
        await controller.callback(
          'not-base64-json',
          mockRequest as Request,
          mockResponse as Response,
          mockNext,
        );

        expect(passport.authenticate).not.toHaveBeenCalled();
        expect(mockResponse.status).toHaveBeenCalledWith(401);
      });
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
        await controller.callback('', mockRequest as Request, mockResponse as Response, mockNext);

        expect(passport.authenticate).not.toHaveBeenCalled();
        expect(mockResponse.status).toHaveBeenCalledWith(401);
        expect(mockResponse.json).toHaveBeenCalledWith({
          error: 'Authentication failed',
          error_description: 'This sign-in was not started in this browser.',
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
