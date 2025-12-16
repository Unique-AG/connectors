import { defaultLoggerOptions } from '@unique-ag/logger';
import { ProbeModule } from '@unique-ag/probe';
import { Module } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { typeid } from 'typeid-js';
import * as packageJson from '../package.json';
import { AppConfig, AppSettings, validateConfig } from './app-settings.enum';
import { ScopedAPIController } from './scoped/scoped-api.controller';

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
  ],
  controllers: [ScopedAPIController],
  providers: [],
})
export class AppModule {}
