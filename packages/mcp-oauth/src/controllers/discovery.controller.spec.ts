import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OAUTH_ENDPOINTS } from '../constants/oauth.constants';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';
import { DiscoveryController } from './discovery.controller';

describe('DiscoveryController', () => {
  let controller: DiscoveryController;
  let mockOptions: McpOAuthModuleOptions;

  beforeEach(async () => {
    mockOptions = {
      hmacSecret: 'test-secret',
      authCodeExpiresIn: 600,
      accessTokenExpiresIn: 3600,
      refreshTokenExpiresIn: 86400,
      oauthSessionExpiresIn: 600000,
      serverUrl: 'https://auth.example.com',
      resource: 'https://mcp.example.com',
      clientId: 'test-client',
      clientSecret: 'test-secret',
      accessTokenFormat: 'opaque',
      jwtSigningKeyProvider: vi.fn(),
      idTokenExpiresIn: 3600,
      protectedResourceMetadata: {
        scopesSupported: ['offline_access', 'mcp:read', 'mcp:write'],
        bearerMethodsSupported: ['header', 'body'],
        mcpVersionsSupported: ['2025-06-18', '2024-11-05'],
        resourceName: 'Example MCP Server',
        resourceDocumentation: 'https://docs.example.com',
        resourcePolicyUri: 'https://example.com/policy',
        resourceTosUri: 'https://example.com/tos',
        resourceSigningAlgValuesSupported: ['HS256', 'RS256'],
        tlsClientCertificateBoundAccessTokens: false,
        dpopBoundAccessTokensRequired: false,
      },
      authorizationServerMetadata: {
        responseTypesSupported: ['code'],
        responseModesSupported: ['query', 'fragment'],
        grantTypesSupported: ['authorization_code', 'refresh_token'],
        tokenEndpointAuthMethodsSupported: ['client_secret_basic', 'client_secret_post', 'none'],
        scopesSupported: ['offline_access', 'mcp:read', 'mcp:write'],
        codeChallengeMethodsSupported: ['plain', 'S256'],
        uiLocalesSupported: ['en', 'es', 'fr'],
        claimsSupported: ['sub', 'email', 'name'],
        serviceDocumentation: 'https://docs.example.com/oauth',
        opPolicyUri: 'https://example.com/oauth-policy',
        opTosUri: 'https://example.com/oauth-tos',
        tokenEndpointAuthSigningAlgValuesSupported: ['HS256'],
        dpopSigningAlgValuesSupported: ['RS256', 'ES256'],
        idTokenSigningAlgValuesSupported: ['HS256'],
        subjectTypesSupported: ['public'],
      },
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      encryptionService: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      oauthStore: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      metricService: {} as any,
      // biome-ignore lint/suspicious/noExplicitAny: Mock for testing
      provider: {} as any,
    };

    const { unit } = await TestBed.solitary(DiscoveryController)
      .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
      .impl((stubFn) => ({ ...stubFn(), ...mockOptions }))
      .compile();

    controller = unit;
  });

  describe('getProtectedResourceMetadata', () => {
    it('includes required fields per RFC9728', () => {
      const metadata = controller.getProtectedResourceMetadata();

      expect(metadata.resource).toBe('https://mcp.example.com');
      expect(metadata.authorization_servers).toContain('https://auth.example.com');
      expect(metadata.scopes_supported).toBeDefined();
      expect(metadata.bearer_methods_supported).toBeDefined();
    });

    it('filters out undefined optional fields', async () => {
      const optionsWithoutOptionalFields: McpOAuthModuleOptions = {
        ...mockOptions,
        protectedResourceMetadata: {
          scopesSupported: ['offline_access'],
          bearerMethodsSupported: ['header'],
          mcpVersionsSupported: ['2025-06-18'],
          // Explicitly set optional fields to undefined
          resourceName: undefined,
          resourceDocumentation: undefined,
          resourcePolicyUri: undefined,
          resourceTosUri: undefined,
          resourceSigningAlgValuesSupported: undefined,
          tlsClientCertificateBoundAccessTokens: undefined,
          dpopBoundAccessTokensRequired: undefined,
        },
      };

      const { unit: controllerWithMinimal } = await TestBed.solitary(DiscoveryController)
        .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
        .impl((stubFn) => ({ ...stubFn(), ...optionsWithoutOptionalFields }))
        .compile();

      const metadata = controllerWithMinimal.getProtectedResourceMetadata();

      expect(metadata.resource_documentation).toBeUndefined();
      expect(metadata.resource_policy_uri).toBeUndefined();
      expect(metadata.resource_tos_uri).toBeUndefined();
      expect(metadata.resource_name).toBe('MCP Server'); // Default value from controller
    });
  });

  describe('getAuthorizationServerMetadata', () => {
    it('includes required fields per RFC8414', () => {
      const metadata = controller.getAuthorizationServerMetadata();

      expect(metadata.issuer).toBe('https://auth.example.com');
      expect(metadata.authorization_endpoint).toBeDefined();
      expect(metadata.token_endpoint).toBeDefined();
    });

    it('constructs correct endpoint URLs', () => {
      const metadata = controller.getAuthorizationServerMetadata();

      expect(metadata.authorization_endpoint).toBe(
        `https://auth.example.com${OAUTH_ENDPOINTS.authorize}`,
      );
      expect(metadata.token_endpoint).toBe(`https://auth.example.com${OAUTH_ENDPOINTS.token}`);
      expect(metadata.registration_endpoint).toBe(
        `https://auth.example.com${OAUTH_ENDPOINTS.register}`,
      );
      expect(metadata.revocation_endpoint).toBe(
        `https://auth.example.com${OAUTH_ENDPOINTS.revoke}`,
      );
      expect(metadata.introspection_endpoint).toBe(
        `https://auth.example.com${OAUTH_ENDPOINTS.introspect}`,
      );
    });

    it('filters out undefined optional fields', async () => {
      const minimalOptions: McpOAuthModuleOptions = {
        ...mockOptions,
        authorizationServerMetadata: {
          responseTypesSupported: ['code'],
          responseModesSupported: ['query'],
          grantTypesSupported: ['authorization_code'],
          tokenEndpointAuthMethodsSupported: ['none'],
          scopesSupported: ['offline_access'],
          codeChallengeMethodsSupported: ['S256'],

          tokenEndpointAuthSigningAlgValuesSupported: undefined,
          uiLocalesSupported: undefined,
          claimsSupported: undefined,
          serviceDocumentation: undefined,
          opPolicyUri: undefined,
          opTosUri: undefined,
          dpopSigningAlgValuesSupported: undefined,
          idTokenSigningAlgValuesSupported: ['HS256'],
          subjectTypesSupported: ['public'],
        },
      };

      const { unit: minimalController } = await TestBed.solitary(DiscoveryController)
        .mock<McpOAuthModuleOptions>(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
        .impl((stubFn) => ({ ...stubFn(), ...minimalOptions }))
        .compile();

      const metadata = minimalController.getAuthorizationServerMetadata();

      expect(metadata.ui_locales_supported).toBeUndefined();
      expect(metadata.claims_supported).toBeUndefined();
      expect(metadata.service_documentation).toBeUndefined();
      expect(metadata.dpop_signing_alg_values_supported).toBeUndefined();
    });

    it('mirrors auth methods for introspection and revocation endpoints', () => {
      const metadata = controller.getAuthorizationServerMetadata();

      expect(metadata.introspection_endpoint_auth_methods_supported).toEqual(
        metadata.token_endpoint_auth_methods_supported,
      );
      expect(metadata.revocation_endpoint_auth_methods_supported).toEqual(
        metadata.token_endpoint_auth_methods_supported,
      );
    });
  });
});
