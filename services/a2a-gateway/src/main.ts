import 'reflect-metadata';

import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { Logger } from '@nestjs/common';
import { NestFactory } from '@nestjs/core';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { AppModule } from './app.module.js';
import { GATEWAY_CONFIG, type GatewayConfig } from './config/config.js';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, {
    bufferLogs: true,
    bodyParser: false,
  });
  app.enableShutdownHooks();

  const config = app.get<GatewayConfig>(GATEWAY_CONFIG);
  // Inline A2A file parts are base64 in the JSON-RPC body; the limit also bounds abuse.
  app.useBodyParser('json', { limit: config.maxRequestBytes });
  app.enableCors({
    origin: config.corsAllowedOrigins,
    methods: ['GET', 'PUT', 'POST', 'DELETE'],
    allowedHeaders: ['Authorization', 'Content-Type', 'If-Match'],
  });
  await app.listen(config.port);
  Logger.log(`A2A gateway listening on port ${config.port}`, 'Bootstrap');
}

initOpenTelemetry({
  defaultServiceName: 'a2a-gateway',
  defaultServiceVersion: process.env.npm_package_version ?? '0.0.0',
  includePgInstrumentation: true,
});
void runWithInstrumentation(bootstrap, 'a2a-gateway');
