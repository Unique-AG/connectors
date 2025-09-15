import { Module, RequestMethod } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { context, trace } from '@opentelemetry/api';
import { LoggerModule } from 'nestjs-pino';
import { AppConfig, appConfig } from './app.config';
import { HealthModule } from './health/health.module';
import { Redacted } from './utils/redacted';

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      ignoreEnvFile: true,
      load: [appConfig],
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
  ],
  controllers: [],
  providers: [],
})
export class AppModule {}
