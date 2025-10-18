import { AesGcmEncryptionModule, AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { defaultLoggerOptions } from '@unique-ag/logger';
import { McpAuthJwtGuard, McpOAuthModule } from '@unique-ag/mcp-oauth';
import { McpModule } from '@unique-ag/mcp-server-module';
import { ProbeModule } from '@unique-ag/probe';
import { CACHE_MANAGER, Cache, CacheModule } from '@nestjs/cache-manager';
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { APP_GUARD } from '@nestjs/core';
import { context, trace } from '@opentelemetry/api';
import { MetricService, OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { typeid } from 'typeid-js';
import * as packageJson from '../package.json';
import { AppConfig, AppSettings, validateConfig } from './app-settings.enum';
import { FactsetAuthModule } from './auth/factset-auth.module';
import { McpOAuthStore } from './auth/mcp-oauth.store';
import { createZitadelOAuthProvider } from './auth/zitadel.provider';
import { EstimatesModule } from './estimates/estimates.module';
import { FundamentalsModule } from './fundamentals/fundamentals.module';
import { GlobalPricesModule } from './global-prices/global-prices.module';
import { ManifestController } from './manifest.controller';
import { PrismaModule } from './prisma/prisma.module';
import { PrismaService } from './prisma/prisma.service';
import { serverInstructions } from './server.instructions';
import { StreetAccountNewsModule } from './street-account-news/street-account-news.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      validate: validateConfig,
    }),
    LoggerModule.forRootAsync({
      useFactory: (configService: ConfigService<AppConfig, true>) => {
        return {
          ...defaultLoggerOptions,
          pinoHttp: {
            ...defaultLoggerOptions.pinoHttp,
            level: configService.get(AppSettings.LOG_LEVEL),
            genReqId: () => {
              const ctx = trace.getSpanContext(context.active());
              if (!ctx) return typeid('trace').toString();
              return ctx.traceId;
            },
          },
        };
      },
      inject: [ConfigService],
    }),
    AesGcmEncryptionModule.registerAsync({
      isGlobal: true,
      imports: [ConfigModule],
      useFactory: (configService: ConfigService<AppConfig, true>) => ({
        key: configService.get(AppSettings.ENCRYPTION_KEY),
      }),
      inject: [ConfigService],
    }),
    CacheModule.register({
      isGlobal: true,
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: true,
        apiMetrics: {
          enable: true,
        },
      },
    }),
    McpOAuthModule.forRootAsync({
      imports: [ConfigModule, PrismaModule],
      useFactory: async (
        configService: ConfigService<AppConfig, true>,
        aesService: AesGcmEncryptionService,
        prisma: PrismaService,
        cacheManager: Cache,
        metricService: MetricService,
      ) => ({
        provider: createZitadelOAuthProvider({
          issuer: configService.get(AppSettings.ZITADEL_ISSUER),
          requiredRole: configService.get(AppSettings.ZITADEL_REQUIRED_ROLE),
        }),

        clientId: configService.get(AppSettings.ZITADEL_CLIENT_ID),
        clientSecret: configService.get(AppSettings.ZITADEL_CLIENT_SECRET),
        hmacSecret: configService.get(AppSettings.HMAC_SECRET),

        serverUrl: configService.get(AppSettings.SELF_URL),
        resource: `${configService.get(AppSettings.SELF_URL)}/mcp`,

        accessTokenExpiresIn: configService.get(AppSettings.ACCESS_TOKEN_EXPIRES_IN_SECONDS),
        refreshTokenExpiresIn: configService.get(AppSettings.REFRESH_TOKEN_EXPIRES_IN_SECONDS),

        oauthStore: new McpOAuthStore(prisma, aesService, cacheManager),
        encryptionService: aesService,
        metricService,
      }),
      inject: [ConfigService, AesGcmEncryptionService, PrismaService, CACHE_MANAGER, MetricService],
    }),
    McpModule.forRoot({
      name: 'factset-mcp',
      version: packageJson.version,
      instructions: serverInstructions,
      streamableHttp: {
        enableJsonResponse: false,
        sessionIdGenerator: () => typeid('session').toString(),
        statelessMode: false,
      },
      mcpEndpoint: 'mcp',
    }),
    FactsetAuthModule,
    EstimatesModule,
    FundamentalsModule,
    GlobalPricesModule,
    StreetAccountNewsModule,
    // PromptsModule,
  ],
  controllers: [ManifestController],
  providers: [
    {
      provide: APP_GUARD,
      useClass: McpAuthJwtGuard,
    },
  ],
})
export class AppModule {}
