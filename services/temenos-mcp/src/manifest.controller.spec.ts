import { TestBed } from '@suites/unit';
import { describe, expect, it } from 'vitest';
import { ManifestController } from './manifest.controller';

describe('ManifestController', () => {
  it('returns server manifest information', async () => {
    const { unit } = await TestBed.solitary(ManifestController).compile();

    const result = unit.getServerInfo();

    expect(result).toMatchObject({
      name: '@unique-ag/temenos-mcp',
      type: 'mcp-server',
      endpoints: {
        mcp: '/<api-key>/mcp',
      },
      features: ['Temenos DataHub ODS integration', '49 operational data tools'],
      documentation: {
        readme: 'https://github.com/Unique-AG/connectors/blob/main/services/temenos-mcp/README.md',
        mcp: 'https://modelcontextprotocol.io/',
      },
      timestamp: expect.any(String),
      status: 'running',
    });
  });
});
