import { defaultLoggerOptions } from '@unique-ag/logger';
import { McpModule } from '@unique-ag/mcp-server-module';
import { ProbeModule } from '@unique-ag/probe';
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { APP_GUARD, APP_INTERCEPTOR, APP_PIPE } from '@nestjs/core';
import { context, trace } from '@opentelemetry/api';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { ZodSerializerInterceptor, ZodValidationPipe } from 'nestjs-zod';
import { typeid } from 'typeid-js';
import * as packageJson from '../package.json';
import { type AppConfig, appConfig, kyckrConfig, logsConfig } from './config';
import { KyckrModule } from './kyckr/kyckr.module';
import { ManifestController } from './manifest.controller';
import { McpAccessTokenGuard } from './mcp-access-token.guard';
import { serverInstructions } from './server.instructions';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: process.env.NODE_ENV === 'test' ? '.env.test' : '.env',
      load: [appConfig, kyckrConfig, logsConfig],
    }),
    LoggerModule.forRootAsync({
      inject: [appConfig.KEY],
      useFactory: (config: AppConfig) => ({
        ...defaultLoggerOptions,
        pinoHttp: {
          ...defaultLoggerOptions.pinoHttp,
          level: config.logLevel,
          mixin: () => {
            const span = trace.getActiveSpan();
            if (!span?.isRecording()) {
              return {};
            }
            const ctx = span.spanContext();
            return { trace_id: ctx.traceId, span_id: ctx.spanId, trace_flags: ctx.traceFlags };
          },
          genReqId: () => {
            const ctx = trace.getSpanContext(context.active());
            if (!ctx) {
              return typeid('trace').toString();
            }
            return ctx.traceId;
          },
        },
      }),
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: true,
      },
    }),
    McpModule.forRoot({
      name: 'kyckr-mcp',
      version: packageJson.version,
      instructions: serverInstructions,
      streamableHttp: {
        enableJsonResponse: false,
        sessionIdGenerator: () => typeid('session').toString(),
        statelessMode: false,
      },
      mcpEndpoint: 'mcp',
    }),
    KyckrModule,
  ],
  controllers: [ManifestController],
  providers: [
    { provide: APP_PIPE, useClass: ZodValidationPipe },
    { provide: APP_INTERCEPTOR, useClass: ZodSerializerInterceptor },
    { provide: APP_GUARD, useClass: McpAccessTokenGuard },
  ],
})
export class AppModule {}
