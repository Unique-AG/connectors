import { TestBed } from '@suites/unit';
import * as jwt from 'jsonwebtoken';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { IDTokenService } from './id-token.service';

describe('IDTokenService', () => {
  let service: IDTokenService;
  let options: McpOAuthModuleOptions;

  beforeEach(async () => {
    options = {
      hmacSecret: 'test-hmac-secret',
      jwtSigningKey: 'test-jwt-signing-key',
      jwtSigningAlgorithm: 'HS256',
      idTokenExpiresIn: 3600,
      serverUrl: 'https://auth.example.com',
      resource: 'https://mcp.example.com',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      authCodeExpiresIn: 600,
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      oauthSessionExpiresIn: 600000,
      protectedResourceMetadata: {},
      authorizationServerMetadata: {},
      encryptionService: {},
      oauthStore: {},
      metricService: {},
      provider: {},
    } as McpOAuthModuleOptions;

    const { unit } = await TestBed.solitary(IDTokenService)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl((stubFn) => ({ ...stubFn(), ...options }))
      .compile();

    service = unit;
  });

  describe('generateIDToken', () => {
    it('generates a valid JWT ID token with required claims', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
      });

      expect(idToken).toBeDefined();
      expect(typeof idToken).toBe('string');

      // Verify the token structure
      const parts = idToken.split('.');
      expect(parts).toHaveLength(3); // Header, Payload, Signature

      // Decode and verify claims
      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.iss).toBe('https://auth.example.com');
      expect(decoded.sub).toBe('user-123');
      expect(decoded.aud).toBe('client-456');
      expect(decoded.azp).toBe('client-456');
      expect(decoded.exp).toBeDefined();
      expect(decoded.iat).toBeDefined();
    });

    it('includes nonce when provided', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        nonce: 'random-nonce-123',
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.nonce).toBe('random-nonce-123');
    });

    it('includes auth_time when provided', () => {
      const authTime = Date.now() - 5000; // 5 seconds ago
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        authTime,
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.auth_time).toBe(Math.floor(authTime / 1000));
    });

    it('includes profile claims when profile scope is requested', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        scope: 'openid profile',
        userProfile: {
          username: 'johndoe',
          displayName: 'John Doe',
          avatarUrl: 'https://example.com/avatar.jpg',
        },
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.name).toBe('John Doe');
      expect(decoded.preferred_username).toBe('johndoe');
      expect(decoded.picture).toBe('https://example.com/avatar.jpg');
    });

    it('includes email claims when email scope is requested', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        scope: 'openid email',
        userProfile: {
          email: 'john@example.com',
        },
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.email).toBe('john@example.com');
      expect(decoded.email_verified).toBe(false);
    });

    it('includes all relevant claims when multiple scopes are requested', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        scope: 'openid profile email',
        userProfile: {
          username: 'johndoe',
          email: 'john@example.com',
          displayName: 'John Doe',
          avatarUrl: 'https://example.com/avatar.jpg',
        },
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.name).toBe('John Doe');
      expect(decoded.preferred_username).toBe('johndoe');
      expect(decoded.picture).toBe('https://example.com/avatar.jpg');
      expect(decoded.email).toBe('john@example.com');
      expect(decoded.email_verified).toBe(false);
    });

    it('does not include profile claims without profile scope', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
        scope: 'openid',
        userProfile: {
          username: 'johndoe',
          displayName: 'John Doe',
        },
      });

      const decoded = jwt.decode(idToken) as jwt.JwtPayload;
      expect(decoded.name).toBeUndefined();
      expect(decoded.preferred_username).toBeUndefined();
    });

    it('uses HS256 algorithm by default', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
      });

      const decoded = jwt.decode(idToken, { complete: true }) as jwt.Jwt;
      expect(decoded.header.alg).toBe('HS256');
      expect(decoded.header.typ).toBe('JWT');
      expect(decoded.header.kid).toBe('default');
    });

    it('uses configured JWT signing key when available', () => {
      const idToken = service.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
      });

      // Verify token can be validated with the configured key
      const verified = jwt.verify(idToken, 'test-jwt-signing-key', {
        algorithms: ['HS256'],
      }) as jwt.JwtPayload;

      expect(verified.sub).toBe('user-123');
    });

    it('falls back to HMAC secret when JWT signing key is not configured', async () => {
      // Create service without JWT signing key
      const optionsWithoutKey = {
        ...options,
        jwtSigningKey: undefined,
      };

      const { unit: serviceWithoutKey } = await TestBed.solitary(IDTokenService)
        .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
        .impl((stubFn) => ({ ...stubFn(), ...optionsWithoutKey }))
        .compile();

      const idToken = serviceWithoutKey.generateIDToken({
        userId: 'user-123',
        clientId: 'client-456',
      });

      // Verify token can be validated with HMAC secret
      const verified = jwt.verify(idToken, 'test-hmac-secret', {
        algorithms: ['HS256'],
      }) as jwt.JwtPayload;

      expect(verified.sub).toBe('user-123');
    });

    it('handles errors during token generation gracefully', () => {
      // Mock jwt.sign to throw an error
      const originalSign = jwt.sign;
      vi.spyOn(jwt, 'sign').mockImplementation(() => {
        throw new Error('Signing failed');
      });

      expect(() =>
        service.generateIDToken({
          userId: 'user-123',
          clientId: 'client-456',
        }),
      ).toThrow('Failed to generate ID token');

      // Restore original implementation
      // biome-ignore lint/suspicious/noExplicitAny: need to restore original implementation
            (jwt as any).sign = originalSign;
    });
  });

  describe('validateIDToken', () => {
    let validToken: string;

    beforeEach(() => {
      // Generate a valid token for testing
      validToken = jwt.sign(
        {
          iss: 'https://auth.example.com',
          sub: 'user-123',
          aud: 'client-456',
          exp: Math.floor(Date.now() / 1000) + 3600,
          iat: Math.floor(Date.now() / 1000),
        },
        'test-jwt-signing-key',
        { algorithm: 'HS256' },
      );
    });

    it('validates a valid ID token successfully', () => {
      const claims = service.validateIDToken(validToken);

      expect(claims).toBeDefined();
      expect(claims?.sub).toBe('user-123');
      expect(claims?.aud).toBe('client-456');
      expect(claims?.iss).toBe('https://auth.example.com');
    });

    it('returns null for invalid token signature', () => {
      const invalidToken = jwt.sign(
        {
          iss: 'https://auth.example.com',
          sub: 'user-123',
          aud: 'client-456',
        },
        'wrong-key',
        { algorithm: 'HS256' },
      );

      const claims = service.validateIDToken(invalidToken);
      expect(claims).toBeNull();
    });

    it('returns null for expired token', () => {
      const expiredToken = jwt.sign(
        {
          iss: 'https://auth.example.com',
          sub: 'user-123',
          aud: 'client-456',
          exp: Math.floor(Date.now() / 1000) - 3600, // Expired 1 hour ago
          iat: Math.floor(Date.now() / 1000) - 7200,
        },
        'test-jwt-signing-key',
        { algorithm: 'HS256' },
      );

      const claims = service.validateIDToken(expiredToken);
      expect(claims).toBeNull();
    });

    it('returns null for token with wrong issuer', () => {
      const wrongIssuerToken = jwt.sign(
        {
          iss: 'https://wrong-issuer.com',
          sub: 'user-123',
          aud: 'client-456',
          exp: Math.floor(Date.now() / 1000) + 3600,
          iat: Math.floor(Date.now() / 1000),
        },
        'test-jwt-signing-key',
        { algorithm: 'HS256' },
      );

      const claims = service.validateIDToken(wrongIssuerToken);
      expect(claims).toBeNull();
    });

    it('returns null for malformed token', () => {
      const claims = service.validateIDToken('not.a.valid.token');
      expect(claims).toBeNull();
    });

    it('validates token with all optional claims', () => {
      const fullToken = jwt.sign(
        {
          iss: 'https://auth.example.com',
          sub: 'user-123',
          aud: 'client-456',
          exp: Math.floor(Date.now() / 1000) + 3600,
          iat: Math.floor(Date.now() / 1000),
          auth_time: Math.floor(Date.now() / 1000) - 300,
          nonce: 'nonce-123',
          name: 'John Doe',
          email: 'john@example.com',
          email_verified: true,
        },
        'test-jwt-signing-key',
        { algorithm: 'HS256' },
      );

      const claims = service.validateIDToken(fullToken);

      expect(claims).toBeDefined();
      expect(claims?.nonce).toBe('nonce-123');
      expect(claims?.name).toBe('John Doe');
      expect(claims?.email).toBe('john@example.com');
      expect(claims?.email_verified).toBe(true);
    });
  });
});
