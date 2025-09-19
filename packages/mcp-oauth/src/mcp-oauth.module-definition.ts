import { ConfigurableModuleBuilder } from '@nestjs/common';
import * as z from 'zod';
import { oauthUserProfileSchema } from './interfaces/oauth-provider.interface';

export const mcpOAuthModuleOptionsSchema = z.object({
  provider: z.object({
    name: z.string(),
    displayName: z.string().optional(),
    strategy: z.any().describe('The passport strategy to use for authentication.'),
    strategyOptions: z
      .function({
        input: [
          z.object({
            serverUrl: z.string(),
            clientId: z.string(),
            clientSecret: z.string(),
            callbackPath: z.string().optional(),
          }),
        ],
        output: z.any(),
      })
      .describe('A factory function that returns the strategy options.'),
    profileMapper: z
      .function({
        input: [z.any()],
        output: oauthUserProfileSchema,
      })
      .describe('A function that maps the profile from the strategy to the user profile.'),
  }),

  // Required OAuth Provider Credentials
  clientId: z.string().describe('The client ID of the OAuth provider.'),
  clientSecret: z.string().describe('The client secret of the OAuth provider.'),

  // Required JWT Configuration
  hmacSecret: z.string().describe('The secret key for the MCP Server to sign HMAC tokens.'),

  // OIDC JWT Configuration
  jwtSigningKey: z
    .string()
    .describe('The key for signing JWT ID tokens (RS256 or HS256)')
    .optional(),
  jwtSigningAlgorithm: z
    .enum(['RS256', 'HS256'])
    .prefault('HS256')
    .describe('Algorithm for signing JWT ID tokens'),
  idTokenExpiresIn: z
    .number()
    .prefault(3600)
    .describe('The expiration time of the JWT ID token in seconds. Default is 1 hour.'),

  // Server Configuration
  serverUrl: z.url(),
  resource: z
    .url()
    .describe("should be the endpoint clients connect to, e.g.: 'http://localhost:3000/mcp'"),

  // Token Configuration
  accessTokenExpiresIn: z
    .number()
    .prefault(60)
    .describe('The expiration time of the JWT access token. Default is 60 seconds.'),
  refreshTokenExpiresIn: z
    .number()
    .prefault(30 * 24 * 60 * 60)
    .describe('The expiration time of the JWT refresh token. Default is 30 days.'),

  oauthSessionExpiresIn: z
    .number()
    .prefault(10 * 60 * 1000)
    .describe('The expiration time of the OAuth session in milliseconds. Default is 10 minutes.'),
  authCodeExpiresIn: z
    .number()
    .prefault(10 * 60 * 1000)
    .describe(
      'The expiration time of the authorization code in milliseconds. Default is 10 minutes.',
    ),

  // Protected Resource Metadata Configuration (RFC9728)
  protectedResourceMetadata: z
    .object({
      // Required fields
      scopesSupported: z.array(z.string()).prefault(['openid', 'offline_access']),
      bearerMethodsSupported: z.array(z.string()).prefault(['header']),
      mcpVersionsSupported: z.array(z.string()).prefault(['2025-06-18']),

      // Optional metadata fields
      resourceName: z.string().optional(),
      resourceDocumentation: z.url().optional(),
      resourcePolicyUri: z.url().optional(),
      resourceTosUri: z.url().optional(),

      // Token binding capabilities
      resourceSigningAlgValuesSupported: z.array(z.string()).optional(),
      tlsClientCertificateBoundAccessTokens: z.boolean().optional(),
      dpopBoundAccessTokensRequired: z.boolean().optional(),
    })
    .prefault({}),

  // Authorization Server Metadata Configuration (RFC8414)
  authorizationServerMetadata: z
    .object({
      // Required/core fields (OAuth 2.1 compliant)
      responseTypesSupported: z.array(z.string()).prefault(['code']),
      responseModesSupported: z.array(z.string()).prefault(['query']),
      grantTypesSupported: z.array(z.string()).prefault(['authorization_code', 'refresh_token']),
      tokenEndpointAuthMethodsSupported: z
        .array(z.string())
        .prefault(['client_secret_basic', 'client_secret_post', 'none']),
      scopesSupported: z.array(z.string()).prefault(['openid', 'offline_access']),
      codeChallengeMethodsSupported: z.array(z.string()).prefault(['plain', 'S256']),

      // Token endpoint authentication
      tokenEndpointAuthSigningAlgValuesSupported: z.array(z.string()).optional(),

      // UI and localization
      uiLocalesSupported: z.array(z.string()).optional(),
      claimsSupported: z.array(z.string()).optional(),

      // Service documentation
      serviceDocumentation: z.url().optional(),
      opPolicyUri: z.url().optional(),
      opTosUri: z.url().optional(),

      // DPoP support
      dpopSigningAlgValuesSupported: z.array(z.string()).optional(),

      // OIDC specific metadata
      idTokenSigningAlgValuesSupported: z.array(z.string()).prefault(['HS256', 'RS256']),
      subjectTypesSupported: z.array(z.string()).prefault(['public']),
      userInfoEndpoint: z.url().optional(),
    })
    .prefault({}),

  encryptionService: z
    .any()
    .describe('Encryption service instance implementing IEncryptionService'),
  oauthStore: z.any().describe('OAuth store instance implementing IOAuthStore'),
  metricService: z.any().describe('Metric service instance implementing IMetricService'),
});

export type McpOAuthModuleOptionsInput = z.input<typeof mcpOAuthModuleOptionsSchema>;
export type McpOAuthModuleOptions = z.output<typeof mcpOAuthModuleOptionsSchema>;

// Export tokens for dependency injection
export const ENCRYPTION_SERVICE_TOKEN = Symbol('ENCRYPTION_SERVICE');
export const OAUTH_STORE_TOKEN = Symbol('OAUTH_STORE');
export const METRIC_SERVICE_TOKEN = Symbol('METRIC_SERVICE');

export const {
  ConfigurableModuleClass,
  MODULE_OPTIONS_TOKEN: MCP_OAUTH_MODULE_OPTIONS_TOKEN,
  ASYNC_OPTIONS_TYPE: MCP_OAUTH_MODULE_ASYNC_OPTIONS_TYPE,
} = new ConfigurableModuleBuilder<McpOAuthModuleOptionsInput>()
  .setClassMethodName('forRoot')
  .setExtras({ isGlobal: true }, (definition, extras) => ({
    ...definition,
    global: extras.isGlobal,
  }))
  .build();

export const MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN = Symbol('MCP_OAUTH_MODULE_OPTIONS_RESOLVED');
