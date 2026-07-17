import { join } from 'node:path';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { AppModule } from './app.module';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create<NestExpressApplication>(AppModule);
  app.enableCors({ origin: true });
  app.enableShutdownHooks();
  app.useBodyParser('json', { limit: '2mb' });
  app.useStaticAssets(join(__dirname, 'public'), {
    setHeaders: (response) => {
      response.setHeader('Cache-Control', 'no-store');
    },
  });

  const port = Number.parseInt(process.env.PORT ?? '9542', 10);
  await app.listen(Number.isFinite(port) ? port : 9542, '0.0.0.0');
}

void bootstrap();
