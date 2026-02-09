import { TestBed } from '@suites/unit';
import { describe, expect, it } from 'vitest';
import { ManifestController } from './manifest.controller';

describe('ManifestController', () => {
  it('returns server manifest information', async () => {
    const { unit } = await TestBed.solitary(ManifestController).compile();

    const result = unit.getServerInfo();

    expect(result).toMatchObject({
      name: '@unique-ag/outlook-semantic-mcp',
      description:
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
          'https://github.com/Unique-AG/connectors/blob/main/services/outlook-semantic-mcp/README.md',
        mcp: 'https://modelcontextprotocol.io/',
      },
      timestamp: expect.any(String),
      status: 'running',
    });
  });
});
