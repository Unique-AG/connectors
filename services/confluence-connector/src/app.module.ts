import { defaultLoggerOptions } from '@unique-ag/logger';
import { ProbeModule } from '@unique-ag/probe';
import { UniqueApiModule } from '@unique-ag/unique-api';
import { Module } from '@nestjs/common';
import { tenantStorage } from './tenant';
import { ConfigModule } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { type AppConfig, appConfig } from './config';
import { Redacted } from './utils/redacted';
import { SchedulerModule } from './scheduler/scheduler.module';
import { TenantModule } from './tenant';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [appConfig],
    }),
    UniqueApiModule.forRoot({
      observability: {
        loggerContext: 'UniqueApi',
        metricPrefix: 'confluence_connector_unique_api',
      },
    }),
    TenantModule,
    SchedulerModule,
    LoggerModule.forRootAsync({
      useFactory(appConfigValue: AppConfig) {
        return {
          ...defaultLoggerOptions,
          pinoHttp: {
            ...defaultLoggerOptions.pinoHttp,
            level: appConfigValue.logLevel,
            mixin: () => {
              const tenant = tenantStorage.getStore();
              return tenant ? { tenantName: tenant.name } : {};
            },
            genReqId: () => {
              const ctx = trace.getSpanContext(context.active());
              if (!ctx) {
                return crypto.randomUUID();
              }
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
  ],
  controllers: [],
})
export class AppModule {}
