import { ProbeModule } from '@unique-ag/probe';
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { ConfigDiagnosticsModule } from './config/config-diagnostics.module';
import { healthConfig } from './config/health.config';
import { type ProxyConfig, proxyConfig } from './config/proxy.config';
import {
  type AppConfig,
  appConfig,
  processingConfig,
  type SharepointConfig,
  sharepointConfig,
  type UniqueConfig,
  uniqueConfig,
} from './config/tenant-config-loader';
import { HealthModule } from './health/health.module';
import { createAppLoggerOptions } from './logger-options';
import { ProxyModule } from './proxy';
import { SchedulerModule } from './scheduler/scheduler.module';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [
        appConfig,
        sharepointConfig,
        processingConfig,
        uniqueConfig,
        proxyConfig,
        healthConfig,
      ],
    }),
    ProxyModule,
    ConfigDiagnosticsModule,
    LoggerModule.forRootAsync({
      useFactory: (
        app: AppConfig,
        sharepoint: SharepointConfig,
        unique: UniqueConfig,
        proxy: ProxyConfig,
      ) => createAppLoggerOptions(app, { sharepoint, unique, proxy }),
      inject: [appConfig.KEY, sharepointConfig.KEY, uniqueConfig.KEY, proxyConfig.KEY],
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: true,
      },
    }),
    HealthModule,
    SchedulerModule,
  ],
  controllers: [],
})
export class AppModule {}
