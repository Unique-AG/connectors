import { McpModule, McpTransportType } from '@unique-ag/mcp-server-module';
import { Module } from '@nestjs/common';
import { OpenTelemetryModule } from 'nestjs-otel';
import { ApiController } from './api.controller';
import { DataModule } from './data/data.module';
import { DemoTools } from './demo.tools';
import { StatusController } from './status.controller';

@Module({
  imports: [
    DataModule,
    OpenTelemetryModule.forRoot({
      metrics: {
        hostMetrics: false,
      },
    }),
    McpModule.forRoot({
      name: 'demo-ir-mcp',
      version: '0.1.0',
      instructions:
        'Use these tools to inspect fictional Ascendant Capital investor-relations CRM, calendar, and email data.',
      transport: McpTransportType.STREAMABLE_HTTP,
      streamableHttp: {
        enableJsonResponse: true,
        statelessMode: true,
      },
      mcpEndpoint: 'mcp',
    }),
  ],
  controllers: [ApiController, StatusController],
  providers: [DemoTools],
})
export class AppModule {}
