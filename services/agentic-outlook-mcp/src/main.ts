import './instrumentation';

import { join } from 'node:path';
import { runWithInstrumentation } from '@unique-ag/instrumentation';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger } from 'nestjs-pino';
import { AppEvents } from './app.events';
import { AppModule } from './app.module';
import { AppConfig, AppSettings } from './app-settings';

async function bootstrap() {
  console.log('Bootstrapping Nest application...');
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  const configService = app.get<ConfigService<AppConfig, true>>(ConfigService);

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const port = configService.get(AppSettings.PORT, { infer: true });
  await app.listen(port);
  console.log(`Server is running on http://localhost:${port}`);
  app.get(EventEmitter2).emit(AppEvents.AppReady);
}

void runWithInstrumentation(bootstrap, 'agentic-outlook-mcp');
