import { join } from 'node:path';
import { AggregationType, InstrumentType, initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { json, urlencoded } from 'express';
import { Logger, LoggerErrorInterceptor } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { type AppConfig, appConfig } from './config';

async function bootstrap() {
  const bufferLogs = process.env.APP_BUFFER_LOGS !== 'disabled';
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs });

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);
  app.useGlobalInterceptors(new LoggerErrorInterceptor());

  // We increase the body size limit mainly for the create draft email tool since in that
  // tool the llm needs to add files which are base64 encoded content.
  app.use(json({ limit: '50mb' }));
  app.use(urlencoded({ extended: true, limit: '50mb' }));

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const config = app.get<AppConfig>(appConfig.KEY);
  await app.listen(config.port, () =>
    logger.log(
      `Outlook Semantic MCP server successfully started and listening on http://localhost:${config.port}`,
      'Bootstrap',
    ),
  );
}

initOpenTelemetry({
  defaultServiceName: 'outlook-semantic-mcp',
  defaultServiceVersion: packageJson.version,
  includePgInstrumentation: true,
  views: [
    {
      instrumentType: InstrumentType.HISTOGRAM,
      instrumentName: 'osm_full_sync_run_duration_seconds',
      aggregation: { type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM, options: { boundaries: [5, 15, 30, 60, 120, 300, 600, 900] } },
    },
    {
      instrumentType: InstrumentType.HISTOGRAM,
      instrumentName: 'osm_full_sync_batch_duration_seconds',
      aggregation: { type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM, options: { boundaries: [1, 5, 10, 30, 60, 120, 300] } },
    },
    {
      instrumentType: InstrumentType.HISTOGRAM,
      instrumentName: 'osm_full_sync_directory_sync_duration_seconds',
      aggregation: { type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM, options: { boundaries: [0.1, 0.5, 1, 2, 5, 10, 30] } },
    },
  ],
});
void runWithInstrumentation(bootstrap, 'outlook-semantic-mcp');
