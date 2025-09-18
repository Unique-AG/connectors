import { ProbeModule } from '@unique-ag/probe';
import { Module, RequestMethod } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { LoggerModule } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppConfig, appConfig } from './app.config';
import { AuthModule } from './auth/auth.module';
import { pipelineConfig } from './config/pipeline.config';
import { sharepointConfig } from './config/sharepoint.config';
import { uniqueApiConfig } from './config/unique-api.config';
import { HttpClientModule } from './http-client.module';
import { SchedulerModule } from './scheduler/scheduler.module';
import { SharepointApiModule } from './sharepoint-api/sharepoint-api.module';
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
        const productionTarget = {
          target: 'pino/file',
        };
        const developmentTarget = {
          target: 'pino-pretty',
          options: {
            ignore: 'trace_flags',
          },
        };

        return {
          pinoHttp: {
            renameContext: appConfig.isDev ? 'caller' : undefined,
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
            transport: appConfig.isDev ? developmentTarget : productionTarget,
          },
          exclude: [
            {
              method: RequestMethod.GET,
              path: 'probe',
            },
            {
              method: RequestMethod.GET,
              path: 'metrics',
            },
          ],
        };
      },
      inject: [appConfig.KEY],
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    HttpClientModule,
    SchedulerModule,
    SharepointScannerModule,
    AuthModule,
    SharepointApiModule,
    UniqueApiModule,
  ],
  controllers: [],
})
export class AppModule {}
