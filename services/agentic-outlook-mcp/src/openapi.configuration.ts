import { type INestApplication } from '@nestjs/common';
import { DocumentBuilder, type SwaggerDocumentOptions, SwaggerModule } from '@nestjs/swagger';
import { cleanupOpenApiDoc } from 'nestjs-zod';
import * as packageJson from '../package.json';
import { BatchModule } from './batch/batch.module';
import { SyncModule } from './sync/sync.module';

const config = new DocumentBuilder()
  .setTitle('Agentic Outlook MCP API')
  .setDescription('API for managing Outlook sync and folders')
  .setVersion(packageJson.version)
  .addBearerAuth()
  .build();

const options: SwaggerDocumentOptions = {
  include: [BatchModule, SyncModule],
  operationIdFactory: (_controllerKey: string, methodKey: string) => {
    return `${methodKey}`;
  },
};

export const getSwaggerDocument = (app: INestApplication) => {
  const document = SwaggerModule.createDocument(app, config, options);
  return cleanupOpenApiDoc(document);
};
