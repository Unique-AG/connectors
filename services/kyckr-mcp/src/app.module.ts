import assert from 'node:assert/strict';
import { McpModule, McpTransportType } from '@unique-ag/mcp-server-module';
import { ProbeModule } from '@unique-ag/probe';
import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { APP_INTERCEPTOR, APP_PIPE } from '@nestjs/core';
import { OpenTelemetryModule } from 'nestjs-otel';
import { LoggerModule } from 'nestjs-pino';
import { ZodSerializerInterceptor, ZodValidationPipe } from 'nestjs-zod';
import * as packageJson from '../package.json';
import { appConfig, kyckrConfig } from './config';
import { KyckrModule } from './kyckr/kyckr.module';
import { createAppLoggerOptions } from './logger-options';
import { ManifestController } from './manifest.controller';
import { serverInstructions } from './server.instructions';

// MCP is mounted at `/<api-key>/mcp` (URL path, since Unique's connector validator rejects query/fragment); other paths 404.
const mcpApiKey = process.env.MCP_API_KEY;
// zod throws after route is mounted if the env var is not set
assert.ok(mcpApiKey, 'MCP_API_KEY env var is required');

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: process.env.NODE_ENV === 'test' ? '.env.test' : '.env',
      load: [appConfig, kyckrConfig],
    }),
    LoggerModule.forRootAsync({
      inject: [appConfig.KEY, kyckrConfig.KEY],
      useFactory: createAppLoggerOptions,
    }),
    ProbeModule.forRoot({
      VERSION: packageJson.version,
    }),
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: true,
      },
    }),
    McpModule.forRoot({
      name: 'kyckr-mcp',
      version: packageJson.version,
      instructions: serverInstructions,
      transport: McpTransportType.STREAMABLE_HTTP,
      streamableHttp: {
        enableJsonResponse: true,
        statelessMode: true,
      },
      mcpEndpoint: `${mcpApiKey}/mcp`,
    }),
    KyckrModule,
  ],
  controllers: [ManifestController],
  providers: [
    { provide: APP_PIPE, useClass: ZodValidationPipe },
    { provide: APP_INTERCEPTOR, useClass: ZodSerializerInterceptor },
  ],
})
export class AppModule {}
