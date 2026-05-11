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
            mcp: '/mcp',
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

  it('rejects /mcp requests without a Bearer token', () => {
    return request(app.getHttpServer())
      .post('/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect(403);
  });

  it('rejects /mcp requests with the wrong Bearer token', () => {
    return request(app.getHttpServer())
      .post('/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .set('Authorization', 'Bearer wrong-token')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect(403);
  });

  it('allows /mcp requests with the configured Bearer token', () => {
    return request(app.getHttpServer())
      .post('/mcp')
      .set('Accept', 'application/json, text/event-stream')
      .set('Authorization', 'Bearer test-mcp-access-token')
      .send({ jsonrpc: '2.0', id: 1, method: 'tools/list' })
      .expect((res) => {
        if (res.status === 403) {
          throw new Error('Guard rejected a request with the correct token');
        }
      });
  });
});
