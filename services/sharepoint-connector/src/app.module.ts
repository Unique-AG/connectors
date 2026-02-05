import { defaultLoggerOptions } from '@unique-ag/logger';
import { ProbeModule } from '@unique-ag/probe';
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { ConfigDiagnosticsModule } from './config/config-diagnostics.module';
import { proxyConfig } from './config/proxy.schema';
import {
  AppConfig,
  appConfig,
  processingConfig,
  sharepointConfig,
  uniqueConfig,
} from './config/tenant-config-loader';
import { ProxyModule } from './proxy';
import { SchedulerModule } from './scheduler/scheduler.module';
import { Redacted } from './utils/redacted';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [appConfig, sharepointConfig, processingConfig, uniqueConfig, proxyConfig],
    }),
    ProxyModule,
    ConfigDiagnosticsModule,
    LoggerModule.forRootAsync({
      useFactory(appConfig: AppConfig) {
        return {
          ...defaultLoggerOptions,
          pinoHttp: {
            ...defaultLoggerOptions.pinoHttp,
            level: appConfig.logLevel,
            genReqId: () => {
              const ctx = trace.getSpanContext(context.active());
              if (!ctx) return crypto.randomUUID();
              return ctx.traceId;
            },
            redact: {
              paths: ['req.headers.authorization'],
              censor: (value) => (value instanceof Redacted ? value : new Redacted(value)),
            },
          },
        };
      },
      inject: [appConfig.KEY],
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
    SchedulerModule,
  ],
  controllers: [],
})
export class AppModule {}
