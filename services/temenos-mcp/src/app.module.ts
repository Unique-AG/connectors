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
import { appConfig, temenosConfig } from './config';
import { createAppLoggerOptions } from './logger-options';
import { ManifestController } from './manifest.controller';
import { serverInstructions } from './server.instructions';
import { TemenosModule } from './temenos/temenos.module';

// MCP is mounted at `/<api-key>/mcp` (URL path, since Unique's connector validator rejects query/fragment).
const mcpApiKey = process.env.MCP_API_KEY;
assert.ok(mcpApiKey, 'MCP_API_KEY env var is required');

@Module({
  imports: [
    ConfigModule.forRoot({
      isGlobal: true,
      envFilePath: process.env.NODE_ENV === 'test' ? '.env.test' : '.env',
      load: [appConfig, temenosConfig],
    }),
    LoggerModule.forRootAsync({
      inject: [appConfig.KEY, temenosConfig.KEY],
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
      name: 'temenos-mcp',
      version: packageJson.version,
      instructions: serverInstructions,
      transport: McpTransportType.STREAMABLE_HTTP,
      streamableHttp: {
        enableJsonResponse: true,
        statelessMode: true,
      },
      mcpEndpoint: `${mcpApiKey}/mcp`,
    }),
    TemenosModule,
  ],
  controllers: [ManifestController],
  providers: [
    { provide: APP_PIPE, useClass: ZodValidationPipe },
    { provide: APP_INTERCEPTOR, useClass: ZodSerializerInterceptor },
  ],
})
export class AppModule {}
