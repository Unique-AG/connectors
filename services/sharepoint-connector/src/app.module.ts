import { Module, RequestMethod } from '@nestjs/common';
import { ConfigModule, ConfigService } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { LoggerModule } from 'nestjs-pino';
import { Client } from 'undici';
import { AppConfig, appConfig } from './app.config';
import { AuthModule } from './auth/auth.module';
import { pipelineConfig } from './config/pipeline.config';
import { sharepointConfig } from './config/sharepoint.config';
import { uniqueApiConfig } from './config/unique-api.config';
import { HealthModule } from './health/health.module';
import { SHAREPOINT_HTTP_CLIENT, UNIQUE_HTTP_CLIENT } from './http-client.tokens';
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
              path: 'health',
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
    HealthModule,
    SchedulerModule,
    SharepointScannerModule,
    AuthModule,
    SharepointApiModule,
    UniqueApiModule,
  ],
  controllers: [],
  providers: [
    {
      provide: UNIQUE_HTTP_CLIENT,
      useFactory: (configService: ConfigService) => {
        const baseUrl = configService.get<string>('uniqueApi.ingestionUrl', '');
        const url = new URL(baseUrl);
        return new Client(`${url.protocol}//${url.host}`, {
          bodyTimeout: 30000,
          headersTimeout: 5000,
        });
      },
      inject: [ConfigService],
    },
    {
      provide: SHAREPOINT_HTTP_CLIENT,
      useFactory: (configService: ConfigService) => {
        const apiUrl = configService.get<string>(
          'sharepoint.apiUrl',
          'https://graph.microsoft.com',
        );
        return new Client(apiUrl, {
          bodyTimeout: 30000,
          headersTimeout: 5000,
        });
      },
      inject: [ConfigService],
    },
  ],
})
export class AppModule {}
