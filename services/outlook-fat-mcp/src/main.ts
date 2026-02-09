import { join } from 'node:path';
import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger, LoggerErrorInterceptor } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { type AppConfig, appConfig } from './config';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs: true });

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);
  app.useGlobalInterceptors(new LoggerErrorInterceptor());

  app.enableCors({
    origin: true,
  });

  app.useStaticAssets(join(__dirname, '..', 'public'));

  const config = app.get<AppConfig>(appConfig.KEY);
  await app.listen(config.port, () =>
    {
      console.log(`Outlook Fat MCP server successfully started and listening on http://localhost:${config.port}`,
        'Bootstrap',)
      logger.log(
        `Outlook Fat MCP server successfully started and listening on http://localhost:${config.port}`,
        'Bootstrap',
      )
    },
  );
  console.log(`HERE ${config.port}`);
}

initOpenTelemetry({
  defaultServiceName: 'outlook-fat-mcp',
  defaultServiceVersion: packageJson.version,
  includePgInstrumentation: true,
});
void runWithInstrumentation(bootstrap, 'outlook-fat-mcp');
