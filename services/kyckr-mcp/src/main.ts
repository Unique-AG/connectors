import { initOpenTelemetry, runWithInstrumentation } from '@unique-ag/instrumentation';
import { NestFactory } from '@nestjs/core';
import { NestExpressApplication } from '@nestjs/platform-express';
import { Logger, LoggerErrorInterceptor } from 'nestjs-pino';
import * as packageJson from '../package.json';
import { AppModule } from './app.module';
import { type AppConfig, appConfig } from './config';

async function bootstrap() {
  const bufferLogs = process.env.APP_BUFFER_LOGS !== 'disabled';
  const app = await NestFactory.create<NestExpressApplication>(AppModule, { bufferLogs });

  app.enableShutdownHooks();

  const logger = app.get(Logger);
  app.useLogger(logger);
  app.useGlobalInterceptors(new LoggerErrorInterceptor());

  app.enableCors({
    origin: true,
  });

  const config = app.get<AppConfig>(appConfig.KEY);
  await app.listen(config.port, () =>
    logger.log(
      `Kyckr MCP server successfully started and listening on http://localhost:${config.port}`,
      'Bootstrap',
    ),
  );
}

initOpenTelemetry({
  defaultServiceName: 'kyckr-mcp',
  defaultServiceVersion: packageJson.version,
});
void runWithInstrumentation(bootstrap, 'kyckr-mcp');
