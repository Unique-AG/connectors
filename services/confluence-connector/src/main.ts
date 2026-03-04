import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { type AppConfigNamespaced } from './config';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });
  const logger = app.get(Logger);
  // All Logger instances app-wide (including shared packages) route through this single pino
  // instance via Logger.staticInstanceRef, so the mixin and log level apply universally.
  app.useLogger(logger);

  const configService = app.get<ConfigService<AppConfigNamespaced, true>>(ConfigService);

  app.enableShutdownHooks();

  app.enableCors({
    origin: true,
  });

  const port = configService.get('app.port', { infer: true });
  await app.listen(port);
  logger.log(`Server is running on http://localhost:${port}`);
}

initOpenTelemetry({
  defaultServiceName: 'confluence-connector',
  defaultServiceVersion: packageJson.version,
});
void runWithInstrumentation(bootstrap, 'confluence-connector');
