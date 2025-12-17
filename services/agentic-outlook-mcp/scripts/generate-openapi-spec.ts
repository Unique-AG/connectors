import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { NestFactory } from '@nestjs/core';
import { AppModule } from '../src/app.module';
import { getSwaggerDocument } from '../src/openapi.configuration';

async function generateSpec() {
  const app = await NestFactory.create(AppModule);

  const outputPath = join(__dirname, '..', 'openapi.json');

  writeFileSync(outputPath, JSON.stringify(getSwaggerDocument(app), null, 2));
  console.log(`OpenAPI spec written to ${outputPath}`);

  await app.close();
  process.exit(0);
}

generateSpec();
