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
          name: '@unique-ag/teams-mcp',
          description: 'Teams MCP Server - Microsoft Graph integration for Model Context Protocol',
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
            'Teams transcripts management',
            'OAuth2 authentication',
            'Secure token handling',
            'RESTful API endpoints',
          ],
          documentation: {
            readme:
              'https://github.com/Unique-AG/connectors/blob/main/services/teams-mcp/README.md',
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
});
