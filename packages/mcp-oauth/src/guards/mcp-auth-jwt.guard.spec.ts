import { ExecutionContext, UnauthorizedException } from '@nestjs/common';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { OpaqueTokenService, type TokenValidationResult } from '../services/opaque-token.service';
import { type McpAuthenticatedRequest, McpAuthJwtGuard } from './mcp-auth-jwt.guard';

describe('McpAuthJwtGuard', () => {
  let guard: McpAuthJwtGuard;
  let tokenService: OpaqueTokenService;
  let options: McpOAuthModuleOptions;
  let mockExecutionContext: ExecutionContext;
  let mockRequest: McpAuthenticatedRequest;

  const mockTokenValidationResult: TokenValidationResult = {
    userId: 'user-123',
    clientId: 'test-client',
    scope: 'offline_access',
    resource: 'http://localhost:3000/mcp',
    userProfileId: 'profile-123',
    userData: { username: 'testuser' },
  };

  beforeEach(async () => {
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
        strategy: vi.fn(),
        strategyOptions: vi.fn(),
        profileMapper: vi.fn(),
      },
    };

    mockRequest = {
      url: '/mcp/tools',
      headers: {},
    } as McpAuthenticatedRequest;

    mockExecutionContext = {
      switchToHttp: vi.fn().mockReturnValue({
        getRequest: vi.fn().mockReturnValue(mockRequest),
      }),
      getType: vi.fn().mockReturnValue('http'),
    } as unknown as ExecutionContext;

    const { unit, unitRef } = await TestBed.solitary(McpAuthJwtGuard)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl((stubFn) => ({ ...stubFn(), ...options }))
      .compile();

    guard = unit;
    tokenService = unitRef.get(OpaqueTokenService);
  });

  describe('canActivate', () => {
    it('allows non-HTTP contexts to pass through without authentication', async () => {
      mockRequest.url = '/health';

      const mockExecutionContext = {
        switchToHttp: vi.fn().mockReturnValue({
          getRequest: vi.fn().mockReturnValue(mockRequest),
        }),
        getType: vi.fn().mockReturnValue('rmq'),
      } as unknown as ExecutionContext;
      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).not.toHaveBeenCalled();
    });

    it('allows non-MCP requests to pass through without authentication', async () => {
      mockRequest.url = '/health';

      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).not.toHaveBeenCalled();
    });

    it('allows requests to non-MCP endpoints starting with /mcp but not exactly /mcp', async () => {
      mockRequest.url = '/mcpother/tools';

      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).not.toHaveBeenCalled();
    });

    it('throws UnauthorizedException when no authorization header is present for MCP requests', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = {};

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Access token required'),
      );
    });

    it('throws UnauthorizedException when authorization header is not Bearer type', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'Basic token123' };

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Access token required'),
      );
    });

    it('throws UnauthorizedException when authorization header is malformed', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'Bearer' };

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Access token required'),
      );
    });

    it('throws UnauthorizedException when token validation fails', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'Bearer invalid-token' };
      vi.mocked(tokenService.validateAccessToken).mockResolvedValue(null);

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Invalid or expired access token'),
      );

      expect(tokenService.validateAccessToken).toHaveBeenCalledWith('invalid-token');
    });

    it('throws UnauthorizedException when token resource does not match configured resource', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'Bearer valid-token' };
      const invalidResourceResult = {
        ...mockTokenValidationResult,
        resource: 'http://different-server.com/mcp',
      };
      vi.mocked(tokenService.validateAccessToken).mockResolvedValue(invalidResourceResult);

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException(
          'Token not valid for this resource. Token was issued for a different resource.',
        ),
      );

      expect(tokenService.validateAccessToken).toHaveBeenCalledWith('valid-token');
    });

    it('allows access and sets user data when token is valid and resource matches', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'Bearer valid-token' };
      vi.mocked(tokenService.validateAccessToken).mockResolvedValue(mockTokenValidationResult);

      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).toHaveBeenCalledWith('valid-token');
      expect(mockRequest.user).toEqual(mockTokenValidationResult);
    });

    it('handles MCP root endpoint correctly', async () => {
      mockRequest.url = '/mcp';
      mockRequest.headers = { authorization: 'Bearer valid-token' };
      vi.mocked(tokenService.validateAccessToken).mockResolvedValue(mockTokenValidationResult);

      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).toHaveBeenCalledWith('valid-token');
      expect(mockRequest.user).toEqual(mockTokenValidationResult);
    });

    it('handles MCP nested endpoints correctly', async () => {
      mockRequest.url = '/mcp/prompts/list';
      mockRequest.headers = { authorization: 'Bearer valid-token' };
      vi.mocked(tokenService.validateAccessToken).mockResolvedValue(mockTokenValidationResult);

      const result = await guard.canActivate(mockExecutionContext);

      expect(result).toBe(true);
      expect(tokenService.validateAccessToken).toHaveBeenCalledWith('valid-token');
      expect(mockRequest.user).toEqual(mockTokenValidationResult);
    });

    it('rejects authorization header with extra leading/trailing spaces', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: '  Bearer   valid-token  ' };

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Access token required'),
      );

      expect(tokenService.validateAccessToken).not.toHaveBeenCalled();
    });

    it('handles case-sensitive Bearer token type', async () => {
      mockRequest.url = '/mcp/tools';
      mockRequest.headers = { authorization: 'bearer valid-token' };

      await expect(guard.canActivate(mockExecutionContext)).rejects.toThrow(
        new UnauthorizedException('Access token required'),
      );

      expect(tokenService.validateAccessToken).not.toHaveBeenCalled();
    });
  });

  describe('extractTokenFromHeader', () => {
    it('extracts Bearer token correctly', () => {
      const request = {
        headers: { authorization: 'Bearer test-token-123' },
      };

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      const token = (guard as any).extractTokenFromHeader(request);

      expect(token).toBe('test-token-123');
    });

    it('returns undefined when no authorization header is present', () => {
      const request = { headers: {} };

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      const token = (guard as any).extractTokenFromHeader(request);

      expect(token).toBeUndefined();
    });

    it('returns undefined when authorization header is not Bearer type', () => {
      const request = {
        headers: { authorization: 'Basic wrongCredentials123' },
      };

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      const token = (guard as any).extractTokenFromHeader(request);

      expect(token).toBeUndefined();
    });

    it('returns undefined when authorization header is malformed', () => {
      const request = {
        headers: { authorization: 'Bearer' },
      };

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      const token = (guard as any).extractTokenFromHeader(request);

      expect(token).toBeUndefined();
    });
  });
});
