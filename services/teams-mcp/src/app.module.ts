import { AesGcmEncryptionModule, AesGcmEncryptionService } from '@unique-ag/aes-gcm-encryption';
import { defaultLoggerOptions } from '@unique-ag/logger';
import { McpAuthJwtGuard, McpOAuthModule } from '@unique-ag/mcp-oauth';
import { McpModule } from '@unique-ag/mcp-server-module';
import { ProbeModule } from '@unique-ag/probe';
import { CACHE_MANAGER, CacheModule } from '@nestjs/cache-manager';
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { APP_GUARD, APP_INTERCEPTOR, APP_PIPE } from '@nestjs/core';
import { EventEmitter2, EventEmitterModule } from '@nestjs/event-emitter';
import { context, trace } from '@opentelemetry/api';
import { Cache } from 'cache-manager';
import { MetricService, OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { ZodSerializerInterceptor, ZodValidationPipe } from 'nestjs-zod';
import { typeid } from 'typeid-js';
import * as packageJson from '../package.json';
import { AMQPModule } from './amqp/amqp.module';
import { McpOAuthStore } from './auth/mcp-oauth.store';
import { MicrosoftOAuthProvider } from './auth/microsoft.provider';
import {
  type AppConfig,
  type AppConfigNamespaced,
  type AuthConfigNamespaced,
  amqpConfig,
  appConfig,
  authConfig,
  databaseConfig,
  type EncryptionConfig,
  encryptionConfig,
  type MicrosoftConfigNamespaced,
  microsoftConfig,
  uniqueConfig,
} from './config';
import { DRIZZLE, DrizzleDatabase, DrizzleModule } from './drizzle/drizzle.module';
import { ManifestController } from './manifest.controller';
import { MsGraphModule } from './msgraph/msgraph.module';
import { serverInstructions } from './server.instructions';
import { TranscriptModule } from './transcript/transcript.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: process.env.NODE_ENV === 'test' ? '.env.test' : '.env',
      load: [amqpConfig, appConfig, authConfig, databaseConfig, encryptionConfig, microsoftConfig, uniqueConfig],
    }),
    LoggerModule.forRootAsync({
      inject: [appConfig.KEY],
      useFactory: (config: AppConfig) => {
        return {
          ...defaultLoggerOptions,
          pinoHttp: {
            ...defaultLoggerOptions.pinoHttp,
            level: config.logLevel,
            genReqId: () => {
              const ctx = trace.getSpanContext(context.active());
              if (!ctx) return typeid('trace').toString();
              return ctx.traceId;
            },
          },
        };
      },
    }),
    AesGcmEncryptionModule.registerAsync({
      isGlobal: true,
      inject: [encryptionConfig.KEY],
      useFactory: (config: EncryptionConfig) => ({
        key: config.key.value,
      }),
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
      },
    }),
    EventEmitterModule.forRoot(),
    McpOAuthModule.forRootAsync({
      imports: [DrizzleModule],
      inject: [ConfigService, AesGcmEncryptionService, DRIZZLE, CACHE_MANAGER, MetricService, EventEmitter2],
      useFactory: async (
        configService: ConfigService<
          AppConfigNamespaced & MicrosoftConfigNamespaced & AuthConfigNamespaced,
          true
        >,
        aesService: AesGcmEncryptionService,
        drizzle: DrizzleDatabase,
        cacheManager: Cache,
        metricService: MetricService,
        emitter: EventEmitter2
      ) => ({
        provider: MicrosoftOAuthProvider,

        clientId: configService.get('microsoft.clientId', { infer: true }),
        clientSecret: configService.get('microsoft.clientSecret', { infer: true }).value,
        hmacSecret: configService.get('auth.hmacSecret', { infer: true }).value,

        serverUrl: configService.get('app.selfUrl', { infer: true }).toString().slice(0, -1),
        resource: new URL("/mcp", configService.get('app.selfUrl', { infer: true })).toString(),

        accessTokenExpiresIn: configService.get('auth.accessTokenExpiresInSeconds', {
          infer: true,
        }),
        refreshTokenExpiresIn: configService.get('auth.refreshTokenExpiresInSeconds', {
          infer: true,
        }),

        oauthStore: new McpOAuthStore(drizzle, aesService, cacheManager, emitter),
        encryptionService: aesService,
        metricService,
      }),
    }),
    McpModule.forRoot({
      name: 'teams-mcp',
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
    AMQPModule,
    TranscriptModule,
  ],
  controllers: [ManifestController],
  providers: [
    { provide: APP_GUARD, useClass: McpAuthJwtGuard },
    { provide: APP_PIPE, useClass: ZodValidationPipe },
    { provide: APP_INTERCEPTOR, useClass: ZodSerializerInterceptor },
  ],
})
export class AppModule {}
