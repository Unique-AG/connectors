import { McpModule } from '@unique-ag/mcp-server-module';
import type { INestApplication } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { Test } from '@nestjs/testing';
import { OpenTelemetryModule } from 'nestjs-otel';
import request from 'supertest';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { kyckrConfig } from '~/config';
import { KyckrModule } from '../kyckr.module';
import { KyckrApiError, KyckrHttpClient } from '../kyckr-http.client';

const mockKyckrClient = { get: vi.fn(), post: vi.fn() };

interface WireContent {
  type: string;
  text: string;
}

interface WireResult {
  content: WireContent[];
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
}

function expectOneJsonItem(result: WireResult) {
  expect(result.content).toEqual([
    { type: 'text', text: JSON.stringify(result.structuredContent) },
  ]);
}

describe('Kyckr tool results on the MCP wire', () => {
  let app: INestApplication;

  async function callTool(name: string, args: Record<string, unknown>): Promise<WireResult> {
    const response = await request(app.getHttpServer())
      .post('/test-kyckr-mcp-key/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } })
      .expect(200);
    return response.body.result;
  }

  beforeAll(async () => {
    const moduleFixture = await Test.createTestingModule({
      imports: [
        ConfigModule.forRoot({ isGlobal: true, ignoreEnvFile: true, load: [kyckrConfig] }),
        OpenTelemetryModule.forRoot(),
        McpModule.forRoot({
          name: 'kyckr-mcp',
          version: '0.0.0',
          streamableHttp: { enableJsonResponse: true, statelessMode: true },
          mcpEndpoint: 'test-kyckr-mcp-key/mcp',
        }),
        KyckrModule,
      ],
    })
      .overrideProvider(KyckrHttpClient)
      .useValue(mockKyckrClient)
      .compile();
    app = moduleFixture.createNestApplication({ logger: false });
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('sends each company found by search_companies with its title', async () => {
    mockKyckrClient.get.mockResolvedValueOnce({
      correlationId: 'corr-1',
      cost: { type: 'credit', value: 0 },
      data: [
        { id: 'GB|123', companyName: 'Acme Ltd', status: 'Active' },
        { id: 'JP|456', companyName: '', englishName: 'Acme Japan KK' },
      ],
    });

    const result = await callTool('search_companies', { name: 'Acme' });

    expect(result.structuredContent).toEqual({
      success: true,
      correlationId: 'corr-1',
      cost: { type: 'credit', value: 0 },
      data: [
        { id: 'GB|123', companyName: 'Acme Ltd', status: 'Active', title: 'Acme Ltd' },
        { id: 'JP|456', companyName: '', englishName: 'Acme Japan KK', title: 'Acme Japan KK' },
      ],
    });
    expectOneJsonItem(result);
  });

  it('sends each order of a list_orders page with its title', async () => {
    mockKyckrClient.get.mockResolvedValueOnce({
      data: {
        pageNumber: 2,
        pageSize: 1,
        totalCount: 3,
        orders: [
          {
            orderId: 7,
            productDetails: { productName: 'Annual Accounts 2025' },
            companyDetails: { companyName: 'Acme Ltd' },
          },
        ],
      },
    });

    const result = await callTool('list_orders', {});

    expect(result.structuredContent).toMatchObject({
      pageNumber: 2,
      totalCount: 3,
      data: [{ orderId: 7, title: 'Annual Accounts 2025 - Acme Ltd' }],
    });
    expectOneJsonItem(result);
  });

  it('sends a profile with the company as its title', async () => {
    mockKyckrClient.get.mockResolvedValueOnce({
      cost: { type: 'credit', value: 2 },
      data: { companyName: 'Acme Ltd', companyNumber: '123' },
    });

    const result = await callTool('get_lite_profile', { kyckrId: 'GB|123' });

    expect(result.structuredContent).toMatchObject({
      title: 'Acme Ltd',
      data: { companyNumber: '123' },
    });
    expectOneJsonItem(result);
  });

  it('sends an order with its product and company as its title', async () => {
    mockKyckrClient.get.mockResolvedValueOnce({
      data: {
        orderId: 'ORD-1',
        status: 'Pending',
        productDetails: { productName: 'Annual Accounts 2025' },
        companyDetails: { companyName: 'Acme Ltd' },
      },
    });

    const result = await callTool('get_order', { orderId: 'ORD-1' });

    expect(result.structuredContent).toMatchObject({ title: 'Annual Accounts 2025 - Acme Ltd' });
    expectOneJsonItem(result);
  });

  it('sends a search without matches unchanged', async () => {
    mockKyckrClient.get.mockResolvedValueOnce({ data: [] });

    const result = await callTool('search_companies', { name: 'Nothing' });

    expect(result.content).toEqual([
      { type: 'text', text: JSON.stringify({ success: true, data: [] }) },
    ]);
    expect(result.structuredContent).toEqual({ success: true, data: [] });
  });

  it('sends a Kyckr error unchanged', async () => {
    mockKyckrClient.get.mockRejectedValueOnce(
      new KyckrApiError(404, '/companies/GB%7C999/lite', 'Company not found', 'corr-404'),
    );

    const result = await callTool('get_lite_profile', { kyckrId: 'GB|999' });

    const failure = {
      success: false,
      statusCode: 404,
      message: 'Company not found',
      correlationId: 'corr-404',
    };
    expect(result.content).toEqual([{ type: 'text', text: JSON.stringify(failure) }]);
    expect(result.structuredContent).toEqual(failure);
  });
});
