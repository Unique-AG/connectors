import { defaultLoggerOptions } from '@unique-ag/logger';
import { ProbeModule } from '@unique-ag/probe';
import { Module, RequestMethod } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppConfig, appConfig } from './app.config';
import { AuthModule } from './auth/auth.module';
import { pipelineConfig } from './config/pipeline.config';
import { sharepointConfig } from './config/sharepoint.config';
import { uniqueApiConfig } from './config/unique-api.config';
import { HttpClientModule } from './http-client.module';
import { MsGraphModule } from './msgraph/msgraph.module';
import { SchedulerModule } from './scheduler/scheduler.module';
import { SharepointScannerModule } from './sharepoint-scanner/sharepoint-scanner.module';
import { UniqueApiModule } from './unique-api/unique-api.module';
import { Redacted } from './utils/redacted';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [appConfig, sharepointConfig, pipelineConfig, uniqueApiConfig],
    }),
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
    HttpClientModule,
    SchedulerModule,
    SharepointScannerModule,
    AuthModule,
    MsGraphModule,
    UniqueApiModule,
  ],
  controllers: [],
})
export class AppModule {}
