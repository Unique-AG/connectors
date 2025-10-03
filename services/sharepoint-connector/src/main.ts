import { join } from 'node:path';
import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppConfigNamespaced } from './config/app.config';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  const configService = app.get<ConfigService<AppConfigNamespaced, true>>(ConfigService);

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const port = configService.get('app.port', { infer: true });
  await app.listen(port);
  logger.log(`Server is running on http://localhost:${port}`);
}

initOpenTelemetry({
  defaultServiceName: 'sharepoint-connector',
  defaultServiceVersion: packageJson.version,
  includePrismaInstrumentation: false,
});
void runWithInstrumentation(bootstrap, 'sharepoint-connector');
