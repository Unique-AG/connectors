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
      description:
        packageJson.description ||
        'Outlook Fat MCP Server - Microsoft Graph integration for Model Context Protocol',
      type: 'mcp-server',
      endpoints: {
        mcp: '/mcp',
        auth: '/auth',
        favicon: '/favicon.ico',
        manifest: '/site.webmanifest',
        icons: '/icons/',
      },
      features: [
        'Microsoft Graph integration',
        'Outlook email management',
        'OAuth2 authentication',
        'Secure token handling',
        'RESTful API endpoints',
      ],
      documentation: {
        readme:
          'https://github.com/Unique-AG/connectors/blob/main/services/outlook-fat-mcp/README.md',
        mcp: 'https://modelcontextprotocol.io/',
      },
      timestamp: new Date().toISOString(),
      status: 'running',
    };
  }
}
