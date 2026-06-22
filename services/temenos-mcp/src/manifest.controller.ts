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
      description: packageJson.description || 'Temenos DataHub MCP Server',
      type: 'mcp-server',
      endpoints: {
        mcp: '/<api-key>/mcp',
      },
      features: ['Temenos DataHub ODS integration', '49 operational data tools'],
      documentation: {
        readme:
          'https://github.com/Unique-AG/connectors/blob/main/services/temenos-mcp/README.md',
        mcp: 'https://modelcontextprotocol.io/',
      },
      timestamp: new Date().toISOString(),
      status: 'running',
    };
  }
}
