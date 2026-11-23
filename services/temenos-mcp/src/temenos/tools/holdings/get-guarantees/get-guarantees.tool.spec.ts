import { McpModule, McpTransportType } from '@unique-ag/mcp-server-module';
import type { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Metrics } from '../../../metrics';
import { TemenosApiError, TemenosHttpClient } from '../../../temenos-http.client';
import { GetGuaranteesQuery } from './get-guarantees.query';
import { GetGuaranteesTool } from './get-guarantees.tool';

const mockHeader = { page_start: 1, page_size: 2, total_size: 5, page_token: 'p2' };
const northwind = { guaranteeId: 'GT2026001', customerName: 'Northwind Traders', amount: 50000 };
const contoso = { guaranteeId: 'GT2026002', customerName: 'Contoso', amount: 12000 };

describe('get_guarantees over MCP', () => {
  let app: INestApplication;
  const get = vi.fn();

  beforeEach(async () => {
    const moduleFixture = await Test.createTestingModule({
      imports: [
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'temenos-mcp-test',
          version: '1.0.0',
          transport: McpTransportType.STREAMABLE_HTTP,
          streamableHttp: { enableJsonResponse: true, statelessMode: true },
        }),
      ],
      providers: [
        GetGuaranteesTool,
        GetGuaranteesQuery,
        { provide: TemenosHttpClient, useValue: { get } },
        { provide: Metrics, useValue: { recordToolDuration: vi.fn() } },
      ],
    }).compile();

    app = moduleFixture.createNestApplication({ logger: false });
    await app.listen(0, '127.0.0.1');
  });

  afterEach(async () => {
    get.mockReset();
    await app.close();
  });

  async function callGetGuarantees(): Promise<unknown> {
    const response = await fetch(`${await app.getUrl()}/mcp`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        accept: 'application/json, text/event-stream',
        'mcp-protocol-version': '2025-06-18',
      },
      body: JSON.stringify({
        jsonrpc: '2.0',
        id: 1,
        method: 'tools/call',
        params: { name: 'get_guarantees', arguments: {} },
      }),
    });
    const body = (await response.json()) as { result: unknown };
    return body.result;
  }

  it('sends the titled guarantees and the header as structured content and one JSON text item', async () => {
    get.mockResolvedValue({ header: mockHeader, body: [northwind, contoso] });

    const result = await callGetGuarantees();

    const guarantees = {
      success: true,
      data: [
        { title: 'Guarantee GT2026001 - Northwind Traders', record: northwind },
        { title: 'Guarantee GT2026002 - Contoso', record: contoso },
      ],
      header: mockHeader,
    };
    expect(result).toEqual({
      structuredContent: guarantees,
      content: [{ type: 'text', text: JSON.stringify(guarantees) }],
    });
  });

  it('sends a Temenos error as one text item', async () => {
    get.mockRejectedValue(new TemenosApiError(404, '/holdings/guarantees/requests', 'Not found'));

    const result = await callGetGuarantees();

    const error = { success: false, statusCode: 404, message: 'Not found' };
    expect(result).toEqual({
      structuredContent: error,
      content: [{ type: 'text', text: JSON.stringify(error) }],
    });
  });
});
