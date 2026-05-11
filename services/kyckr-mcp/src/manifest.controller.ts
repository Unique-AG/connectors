import { Controller, Get, Header } from '@nestjs/common';
import * as packageJson from '../package.json';

@Controller()
export class ManifestController {
  @Get()
  @Header('Cache-Control', 'public, max-age=3600')
  public getServerInfo() {
    return {
      name: packageJson.name,
      version: packageJson.version,
      description: packageJson.description || 'Kyckr MCP Server - company registry data via MCP',
      type: 'mcp-server',
      endpoints: {
        mcp: '/mcp',
      },
      features: ['Kyckr company registry integration', 'KYC/KYB data retrieval'],
      documentation: {
        readme: 'https://github.com/Unique-AG/connectors/blob/main/services/kyckr-mcp/README.md',
        mcp: 'https://modelcontextprotocol.io/',
      },
      timestamp: new Date().toISOString(),
      status: 'running',
    };
  }
}
