import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { cleanupOpenApiDoc } from 'nestjs-zod';
import * as packageJson from '../package.json';
import { AppModule } from '../src/app.module';
import { SyncModule } from '../src/sync/sync.module';

async function generateSpec() {
  const app = await NestFactory.create(AppModule, {
    logger: false,
  });

  const config = new DocumentBuilder()
    .setTitle('Agentic Outlook MCP API')
    .setDescription('API for managing Outlook sync and folders')
    .setVersion(packageJson.version)
    .addBearerAuth()
    .build();

  const document = SwaggerModule.createDocument(app, config, {
    include: [SyncModule],
  });
  const outputPath = join(__dirname, '..', 'openapi.json');

  writeFileSync(outputPath, JSON.stringify(cleanupOpenApiDoc(document), null, 2));
  console.log(`OpenAPI spec written to ${outputPath}`);

  await app.close();
  process.exit(0);
}

generateSpec();
