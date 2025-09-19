import { Controller, Get, Header, Inject, UseGuards } from '@nestjs/common';
import { SkipThrottle, ThrottlerGuard } from '@nestjs/throttler';
import { OAUTH_ENDPOINTS } from '../constants/oauth.constants';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

@Controller('.well-known')
@UseGuards(ThrottlerGuard)
@SkipThrottle()
export class DiscoveryController {
  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  /**
   * Protected Resource Metadata endpoint as defined in RFC9728.
   * This endpoint describes the protected MCP server resource.
   */
  @Get(['oauth-protected-resource', 'oauth-protected-resource/mcp'])
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  public getProtectedResourceMetadata() {
    const metadata = {
      // Required fields per RFC9728
      resource: this.options.resource,
      authorization_servers: [this.options.serverUrl],

      // OAuth 2.0 capabilities
      scopes_supported: this.options.protectedResourceMetadata.scopesSupported,
      bearer_methods_supported: this.options.protectedResourceMetadata.bearerMethodsSupported,

      // MCP-specific extensions
      mcp_versions_supported: this.options.protectedResourceMetadata.mcpVersionsSupported,

      // Optional
      resource_name: this.options.protectedResourceMetadata.resourceName || 'MCP Server',
      resource_documentation: this.options.protectedResourceMetadata.resourceDocumentation,
      resource_policy_uri: this.options.protectedResourceMetadata.resourcePolicyUri,
      resource_tos_uri: this.options.protectedResourceMetadata.resourceTosUri,

      // Token binding capabilities
      resource_signing_alg_values_supported: this.options.protectedResourceMetadata
        .resourceSigningAlgValuesSupported || ['HS256'],
      tls_client_certificate_bound_access_tokens:
        this.options.protectedResourceMetadata.tlsClientCertificateBoundAccessTokens || false,
      dpop_bound_access_tokens_required:
        this.options.protectedResourceMetadata.dpopBoundAccessTokensRequired || false,
    };

    return Object.fromEntries(Object.entries(metadata).filter(([_, value]) => value !== undefined));
  }

  /**
   * OpenID Connect Discovery endpoint as defined in OpenID Connect Discovery 1.0
   * This endpoint describes the OpenID Provider configuration.
   */
  @Get('openid-configuration')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  public getOpenIDConfiguration() {
    const metadata = {
      // Required fields per OpenID Connect Discovery 1.0
      issuer: this.options.serverUrl,
      authorization_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.authorize}`,
      token_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.token}`,
      jwks_uri: `${this.options.serverUrl}/.well-known/jwks.json`,
      
      // Optional endpoints
      registration_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.register}`,
      revocation_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.revoke}`,
      introspection_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.introspect}`,
      userinfo_endpoint: this.options.authorizationServerMetadata.userInfoEndpoint,

      // Supported capabilities
      response_types_supported: this.options.authorizationServerMetadata.responseTypesSupported,
      response_modes_supported: this.options.authorizationServerMetadata.responseModesSupported,
      grant_types_supported: this.options.authorizationServerMetadata.grantTypesSupported,
      subject_types_supported: this.options.authorizationServerMetadata.subjectTypesSupported || ['public'],
      id_token_signing_alg_values_supported: 
        this.options.authorizationServerMetadata.idTokenSigningAlgValuesSupported || ['HS256', 'RS256'],
      scopes_supported: this.options.authorizationServerMetadata.scopesSupported,
      token_endpoint_auth_methods_supported:
        this.options.authorizationServerMetadata.tokenEndpointAuthMethodsSupported,
      claims_supported: this.options.authorizationServerMetadata.claimsSupported || [
        'sub', 'iss', 'aud', 'exp', 'iat', 'auth_time', 'nonce',
        'name', 'preferred_username', 'email', 'email_verified', 'picture',
      ],
      code_challenge_methods_supported:
        this.options.authorizationServerMetadata.codeChallengeMethodsSupported,
      
      // Service documentation
      service_documentation: this.options.authorizationServerMetadata.serviceDocumentation,
      op_policy_uri: this.options.authorizationServerMetadata.opPolicyUri,
      op_tos_uri: this.options.authorizationServerMetadata.opTosUri,

      // UI and localization
      ui_locales_supported: this.options.authorizationServerMetadata.uiLocalesSupported,
      
      // Token characteristics
      access_token_issuer: this.options.serverUrl,
    };

    return Object.fromEntries(Object.entries(metadata).filter(([_, value]) => value !== undefined));
  }

  /**
   * Authorization Server Metadata endpoint as defined in RFC8414.
   * This endpoint describes the OAuth 2.0 authorization server capabilities.
   * This is an alias for the OIDC discovery endpoint for OAuth 2.0 compatibility.
   */
  @Get('oauth-authorization-server')
  @Header('X-Content-Type-Options', 'nosniff')
  @Header('X-Frame-Options', 'DENY')
  public getAuthorizationServerMetadata() {
    const metadata = {
      // Required fields per RFC8414
      issuer: this.options.serverUrl,
      authorization_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.authorize}`,
      token_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.token}`,

      // Optional
      registration_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.register}`,
      revocation_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.revoke}`,
      introspection_endpoint: `${this.options.serverUrl}${OAUTH_ENDPOINTS.introspect}`,

      // Supported capabilities
      response_types_supported: this.options.authorizationServerMetadata.responseTypesSupported,
      response_modes_supported: this.options.authorizationServerMetadata.responseModesSupported,
      grant_types_supported: this.options.authorizationServerMetadata.grantTypesSupported,
      token_endpoint_auth_methods_supported:
        this.options.authorizationServerMetadata.tokenEndpointAuthMethodsSupported,
      token_endpoint_auth_signing_alg_values_supported:
        this.options.authorizationServerMetadata.tokenEndpointAuthSigningAlgValuesSupported,
      introspection_endpoint_auth_methods_supported:
        this.options.authorizationServerMetadata.tokenEndpointAuthMethodsSupported,
      revocation_endpoint_auth_methods_supported:
        this.options.authorizationServerMetadata.tokenEndpointAuthMethodsSupported,

      // Scopes and PKCE support
      scopes_supported: this.options.authorizationServerMetadata.scopesSupported,
      code_challenge_methods_supported:
        this.options.authorizationServerMetadata.codeChallengeMethodsSupported,

      // UI and localization
      ui_locales_supported: this.options.authorizationServerMetadata.uiLocalesSupported,
      claims_supported: this.options.authorizationServerMetadata.claimsSupported,

      // Service documentation
      service_documentation: this.options.authorizationServerMetadata.serviceDocumentation,
      op_policy_uri: this.options.authorizationServerMetadata.opPolicyUri,
      op_tos_uri: this.options.authorizationServerMetadata.opTosUri,

      // Token characteristics
      access_token_issuer: this.options.serverUrl,

      // DPoP support
      dpop_signing_alg_values_supported:
        this.options.authorizationServerMetadata.dpopSigningAlgValuesSupported,
    };

    return Object.fromEntries(Object.entries(metadata).filter(([_, value]) => value !== undefined));
  }
}
