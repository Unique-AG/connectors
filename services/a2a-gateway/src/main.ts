import 'reflect-metadata';

import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module.js';
import { GATEWAY_CONFIG, type GatewayConfig } from './config/config.js';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { bufferLogs: true });
  app.enableShutdownHooks();

  const config = app.get<GatewayConfig>(GATEWAY_CONFIG);
  await app.listen(config.port);
  Logger.log(`A2A gateway listening on port ${config.port}`, 'Bootstrap');
}

void bootstrap();
