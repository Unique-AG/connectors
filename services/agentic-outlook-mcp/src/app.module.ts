import { AesGcmEncryptionModule, AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { defaultLoggerOptions } from '@unique-ag/logger';
import { McpAuthJwtGuard, McpOAuthModule } from '@unique-ag/mcp-oauth';
import { McpModule } from '@unique-ag/mcp-server-module';
import { ProbeModule } from '@unique-ag/probe';
import { CACHE_MANAGER, CacheModule } from '@nestjs/cache-manager';
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { APP_GUARD } from '@nestjs/core';
import { EventEmitterModule } from '@nestjs/event-emitter';
import { ScheduleModule } from '@nestjs/schedule';
import { context, trace } from '@opentelemetry/api';
import { Cache } from 'cache-manager';
import { MetricService, OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { typeid } from 'typeid-js';
import * as packageJson from '../package.json';
import { AppConfig, AppSettings, validateConfig } from './app-settings';
import { McpOAuthStore } from './auth/mcp-oauth.store';
import { MicrosoftOAuthProvider } from './auth/microsoft.provider';
import { BatchModule } from './batch/batch.module';
import { DRIZZLE, DrizzleDatabase, DrizzleModule } from './drizzle/drizzle.module';
import { EmailModule } from './email/email.module';
import { FolderModule } from './folder/folder.module';
import { MailModule } from './mail/mail.module';
import { ManifestController } from './manifest.controller';
import { MsGraphModule } from './msgraph/msgraph.module';
import { serverInstructions } from './server.instructions';
import { SyncModule } from './sync/sync.module';
import { UserModule } from './user/user.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: process.env.NODE_ENV === 'test' ? '.env.test' : '.env',
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
    ScheduleModule.forRoot(),
    EventEmitterModule.forRoot(),
    McpOAuthModule.forRootAsync({
      imports: [ConfigModule, DrizzleModule],
      useFactory: async (
        configService: ConfigService<AppConfig, true>,
        aesService: AesGcmEncryptionService,
        drizzle: DrizzleDatabase,
        cacheManager: Cache,
        metricService: MetricService,
      ) => ({
        provider: MicrosoftOAuthProvider,

        clientId: configService.get(AppSettings.MICROSOFT_CLIENT_ID),
        clientSecret: configService.get(AppSettings.MICROSOFT_CLIENT_SECRET),
        hmacSecret: configService.get(AppSettings.HMAC_SECRET),

        accessTokenFormat: 'jwt',
        jwtSigningKeyProvider: async () => {
          return {
            privateKey: configService.get(AppSettings.JWT_PRIVATE_KEY),
            publicKey: configService.get(AppSettings.JWT_PUBLIC_KEY),
            keyId: configService.get(AppSettings.JWT_KEY_ID),
            algorithm: configService.get(AppSettings.JWT_ALGORITHM),
          };
        },

        serverUrl: configService.get(AppSettings.SELF_URL),
        resource: `${configService.get(AppSettings.SELF_URL)}/mcp`,

        accessTokenExpiresIn: configService.get(AppSettings.ACCESS_TOKEN_EXPIRES_IN_SECONDS),
        refreshTokenExpiresIn: configService.get(AppSettings.REFRESH_TOKEN_EXPIRES_IN_SECONDS),

        oauthStore: new McpOAuthStore(drizzle, aesService, cacheManager),
        encryptionService: aesService,
        metricService,
      }),
      inject: [ConfigService, AesGcmEncryptionService, DRIZZLE, CACHE_MANAGER, MetricService],
    }),
    McpModule.forRoot({
      name: 'agentic-outlook-mcp',
      version: packageJson.version,
      instructions: serverInstructions,
      streamableHttp: {
        enableJsonResponse: false,
        sessionIdGenerator: () => typeid('session').toString(),
        statelessMode: false,
      },
      mcpEndpoint: 'mcp',
    }),
    MsGraphModule,
    MailModule,
    EmailModule,
    BatchModule,
    SyncModule,
    UserModule,
    FolderModule,
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
