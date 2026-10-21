import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, describe, expect, it } from 'vitest';
import { McpModule } from '../src';

const icons = [
  { src: 'data:image/png;base64,iVBORw0KGgo=', mimeType: 'image/png', sizes: ['192x192'] },
];

describe('MCP server icons (E2E)', () => {
  let app: INestApplication;

  afterEach(async () => {
    await app.close();
  });

  async function connectedServerInfo(statelessMode: boolean) {
    const moduleFixture = await Test.createTestingModule({
      imports: [
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'test-mcp',
          version: '1.0.0',
          icons,
          streamableHttp: { enableJsonResponse: false, statelessMode },
        }),
      ],
    }).compile();
    app = moduleFixture.createNestApplication({ logger: false });
    await app.listen(0, '127.0.0.1');

    const client = new Client({ name: 'test-client', version: '1.0.0' });
    await client.connect(new StreamableHTTPClientTransport(new URL(`${await app.getUrl()}/mcp`)));
    const serverInfo = client.getServerVersion();
    await client.close();
    return serverInfo;
  }

  it('advertises icons in serverInfo in stateful mode', async () => {
    expect((await connectedServerInfo(false))?.icons).toEqual(icons);
  });

  it('advertises icons in serverInfo in stateless mode', async () => {
    expect((await connectedServerInfo(true))?.icons).toEqual(icons);
  });
});
