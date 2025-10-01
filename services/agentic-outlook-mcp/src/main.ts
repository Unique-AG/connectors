import { join } from 'node:path';
import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { Logger } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { AppConfig, AppSettings } from './app-settings';
import { SyncModule } from './sync/sync.module';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  const configService = app.get<ConfigService<AppConfig, true>>(ConfigService);

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const config = new DocumentBuilder()
    .setTitle('Agentic Outlook MCP API')
    .setDescription('API for managing Outlook sync and folders')
    .setVersion(packageJson.version)
    .addBearerAuth()
    .build();
  const document = SwaggerModule.createDocument(app, config, {
    include: [SyncModule],
  });
  SwaggerModule.setup('api-docs', app, document);

  const port = configService.get(AppSettings.PORT, { infer: true });
  await app.listen(port);
  console.log(`Server is running on http://localhost:${port}`);
  console.log(`OpenAPI docs available at http://localhost:${port}/api-docs`);
}

initOpenTelemetry({
  defaultServiceName: 'agentic-outlook-mcp',
  defaultServiceVersion: packageJson.version,
  includePgInstrumentation: true,
});
void runWithInstrumentation(bootstrap, 'agentic-outlook-mcp');
