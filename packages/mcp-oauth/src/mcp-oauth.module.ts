import { type DynamicModule, Module, type Provider } from '@nestjs/common';
import { APP_FILTER } from '@nestjs/core';
import { ScheduleModule } from '@nestjs/schedule';
import { seconds, ThrottlerModule } from '@nestjs/throttler';
import { ClientController } from './controllers/client.controller';
import { DiscoveryController } from './controllers/discovery.controller';
import { OAuthController } from './controllers/oauth.controller';
import { TokenController } from './controllers/token.controller';
import { OAuthExceptionFilter } from './filters/oauth-exception.filter';
import { McpAuthJwtGuard } from './guards/mcp-auth-jwt.guard';
import {
  ConfigurableModuleClass,
  ENCRYPTION_SERVICE_TOKEN,
  MCP_OAUTH_MODULE_ASYNC_OPTIONS_TYPE,
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  MCP_OAUTH_MODULE_OPTIONS_TOKEN,
  type McpOAuthModuleOptions,
  type McpOAuthModuleOptionsInput,
  METRIC_SERVICE_TOKEN,
  mcpOAuthModuleOptionsSchema,
  OAUTH_STORE_TOKEN,
} from './mcp-oauth.module-definition';
import { ClientService } from './services/client.service';
import { IDTokenService } from './services/id-token.service';
import { McpOAuthService } from './services/mcp-oauth.service';
import { MetricService } from './services/metric.service';
import { OAuthStrategyService } from './services/oauth-strategy.service';
import { OpaqueTokenService } from './services/opaque-token.service';

/**
 * NestJS module that implements the OAuth 2.1 Authorization Code + PKCE flow for MCP servers.
 *
 * The module expects the following to be provided via the options:
 * - oauthStore: An instance of IOAuthStore for persistent storage
 * - encryptionService: An instance of IEncryptionService for encryption
 *
 * Example usage:
 * ```ts
 * McpOAuthModule.forRootAsync({
 *   imports: [ConfigModule, PrismaModule],
 *   useFactory: async (
 *     configService: ConfigService<AppConfig, true>,
 *     aesService: AesGcmEncryptionService,
 *     prisma: PrismaService,
 *   ) => ({
 *     provider: ExampleOAuthProvider,
 *
 *     clientId: configService.get(AppSettings.CLIENT_ID),
 *     clientSecret: configService.get(AppSettings.CLIENT_SECRET),
 *     hmacSecret: configService.get(AppSettings.HMAC_SECRET),
 *
 *     serverUrl: configService.get(AppSettings.SELF_URL),
 *     resource: configService.get(AppSettings.SELF_URL),
 *
 *     oauthStore: new McpOAuthStore(prisma, aesService),
 *     encryptionService: aesService,
 *   }),
 *   inject: [ConfigService, AesGcmEncryptionService, PrismaService],
 * }),
 * ```
 */
@Module({})
export class McpOAuthModule extends ConfigurableModuleClass {
  public static forRootAsync(options: typeof MCP_OAUTH_MODULE_ASYNC_OPTIONS_TYPE): DynamicModule {
    // biome-ignore lint/complexity/noThisInStatic: That's how NestJS extends the pre-configured rootAsync method.
    const baseModule = super.forRootAsync(options);

    const providers: Provider[] = [
      {
        provide: MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
        useFactory: (rawOptions: McpOAuthModuleOptionsInput) =>
          mcpOAuthModuleOptionsSchema.parse(rawOptions),
        inject: [MCP_OAUTH_MODULE_OPTIONS_TOKEN],
      },
      McpOAuthService,
      ClientService,
      IDTokenService,
      OpaqueTokenService,
      OAuthStrategyService,
      MetricService,
      McpAuthJwtGuard,
      {
        provide: APP_FILTER,
        useClass: OAuthExceptionFilter,
      },
      {
        provide: OAUTH_STORE_TOKEN,
        useFactory: (moduleOptions: McpOAuthModuleOptions) => {
          if (!moduleOptions.oauthStore) {
            throw new Error(
              'OAuth store is required. Please provide an oauthStore instance in the module options.',
            );
          }
          return moduleOptions.oauthStore;
        },
        inject: [MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN],
      },
      {
        provide: ENCRYPTION_SERVICE_TOKEN,
        useFactory: (moduleOptions: McpOAuthModuleOptions) => {
          if (!moduleOptions.encryptionService) {
            throw new Error(
              'Encryption service is required. Please provide an encryptionService instance in the module options.',
            );
          }
          return moduleOptions.encryptionService;
        },
        inject: [MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN],
      },
      {
        provide: METRIC_SERVICE_TOKEN,
        useFactory: (moduleOptions: McpOAuthModuleOptions) => {
          return moduleOptions.metricService;
        },
        inject: [MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN],
      },
    ];

    return {
      ...baseModule,
      module: McpOAuthModule,
      imports: [
        ...(baseModule.imports || []),
        ScheduleModule.forRoot(),
        ThrottlerModule.forRoot({
          throttlers: [
            {
              ttl: seconds(60),
              limit: 10,
            },
          ],
        }),
      ],
      controllers: [DiscoveryController, ClientController, OAuthController, TokenController],
      providers: [...(baseModule.providers || []), ...providers],
      exports: [
        OpaqueTokenService,
        McpAuthJwtGuard,
        OAUTH_STORE_TOKEN,
        ENCRYPTION_SERVICE_TOKEN,
        METRIC_SERVICE_TOKEN,
        MCP_OAUTH_MODULE_OPTIONS_TOKEN,
        MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
      ],
    };
  }
}
