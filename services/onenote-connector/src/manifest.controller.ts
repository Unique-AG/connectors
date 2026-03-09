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
        'OneNote Connector - Microsoft Graph integration for syncing OneNote notebooks',
      type: 'mcp-server',
      endpoints: {
        mcp: '/mcp',
        auth: '/auth',
      },
      features: [
        'Microsoft Graph OneNote integration',
        'Periodic notebook synchronization',
        'Delta-based incremental sync',
        'OneNote page search',
        'Create and update OneNote pages',
        'OAuth2 authentication',
        'Secure token handling',
      ],
      timestamp: new Date().toISOString(),
      status: 'running',
    };
  }
}
