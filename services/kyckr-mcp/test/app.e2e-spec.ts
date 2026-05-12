import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module';

describe('AppController (e2e)', () => {
  let app: INestApplication;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterEach(async () => {
    await app.close();
  });

  it('/ (GET) returns server manifest', () => {
    return request(app.getHttpServer())
      .get('/')
      .expect(200)
      .expect((res) => {
        expect(res.body).toMatchObject({
          name: '@unique-ag/kyckr-mcp',
          type: 'mcp-server',
          endpoints: {
            mcp: '/<api-key>/mcp',
          },
          features: ['Kyckr company registry integration', 'KYC/KYB data retrieval'],
          documentation: {
            readme:
              'https://github.com/Unique-AG/connectors/blob/main/services/kyckr-mcp/README.md',
            mcp: 'https://modelcontextprotocol.io/',
          },
          timestamp: expect.any(String),
          status: 'running',
        });
      });
  });

  it('/probe (GET) returns health status', () => {
    return request(app.getHttpServer()).get('/probe').expect(200);
  });

  it('handles 404 for unknown routes', () => {
    return request(app.getHttpServer()).get('/unknown-route').expect(404);
  });

  it('returns 404 for /mcp without the api-key path prefix', () => {
    return request(app.getHttpServer())
      .post('/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect(404);
  });

  it('returns 404 for a wrong api-key path prefix', () => {
    return request(app.getHttpServer())
      .post('/wrong-api-key/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect(404);
  });

  it('serves /mcp under the configured api-key path prefix', () => {
    return request(app.getHttpServer())
      .post('/test-mcp-api-key/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect((res) => {
        if (res.status === 404) {
          throw new Error('McpModule did not register the route under the api-key prefix');
        }
      });
  });
});
