import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { AppConfig, AppSettings } from './app-settings.enum';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  const configService = app.get<ConfigService<AppConfig, true>>(ConfigService);

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);

  app.enableCors({
    origin: true,
  });

  const port = configService.get(AppSettings.PORT, { infer: true });
  await app.listen(port);
  console.log(`Server is running on http://localhost:${port}`);
}

initOpenTelemetry({
  defaultServiceName: 'sandbox',
  defaultServiceVersion: packageJson.version,
});
void runWithInstrumentation(bootstrap, 'sandbox');
