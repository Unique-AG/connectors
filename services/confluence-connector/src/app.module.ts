import { ProbeModule } from '@unique-ag/probe';
import { UniqueApiModule } from '@unique-ag/unique-api';
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import {
  type AppConfig,
  appConfig,
  getTenantConfigs,
  healthConfig,
  type ProxyConfig,
  proxyConfig,
} from './config';
import { HealthModule } from './health/health.module';
import { createAppLoggerOptions } from './logger-options';
import { ProxyModule } from './proxy';
import { SchedulerModule } from './scheduler/scheduler.module';
import { TenantModule } from './tenant';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [appConfig, proxyConfig, healthConfig],
    }),
    ProxyModule,
    UniqueApiModule.forRoot({
      observability: {
        loggerContext: 'UniqueApi',
        metricPrefix: 'confluence_connector_unique_api',
      },
    }),
    TenantModule,
    HealthModule,
    SchedulerModule,
    LoggerModule.forRootAsync({
      useFactory: (app: AppConfig, proxy: ProxyConfig) =>
        createAppLoggerOptions(app, proxy, getTenantConfigs()),
      inject: [appConfig.KEY, proxyConfig.KEY],
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: true,
      },
    }),
  ],
  controllers: [],
})
export class AppModule {}
