import { join } from 'node:path';
import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger, LoggerErrorInterceptor } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { type AppConfig, appConfig } from './config';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);
  app.useGlobalInterceptors(new LoggerErrorInterceptor());

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const config = app.get<AppConfig>(appConfig.KEY);
  await app.listen(config.port, () =>
    logger.log(`Server is running on http://localhost:${config.port}`, 'Bootstrap'),
  );
}

initOpenTelemetry({
  defaultServiceName: 'teams-mcp',
  defaultServiceVersion: packageJson.version,
  includePgInstrumentation: true,
});
void runWithInstrumentation(bootstrap, 'teams-mcp');
