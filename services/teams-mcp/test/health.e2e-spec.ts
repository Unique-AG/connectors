import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module';
import { RootScopeBootstrapService } from '../src/unique/root-scope-bootstrap.service';

describe('Health endpoint (e2e)', () => {
  let app: INestApplication;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    })
      // The bootstrap hook grants root-scope access against the Unique API at boot;
      // stub it so app.init() does not require a live Unique API for these e2e tests.
      .overrideProvider(RootScopeBootstrapService)
      .useValue({ onApplicationBootstrap: () => Promise.resolve() })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterEach(async () => {
    await app.close();
  });

  it('/health (GET) reports operational status for each dependency', async () => {
    // Terminus returns 200 when every indicator is up and 503 otherwise; either way the body
    // exposes the per-indicator breakdown, which is what we assert on.
    const res = await request(app.getHttpServer()).get('/health');

    expect([200, 503]).toContain(res.status);
    expect(res.body).toMatchObject({
      status: expect.any(String),
      info: expect.any(Object),
      error: expect.any(Object),
      details: expect.any(Object),
    });

    const indicators = res.body.details;
    expect(indicators).toHaveProperty('database');
    expect(indicators).toHaveProperty('amqp');
    expect(indicators).toHaveProperty('connectivity');
    expect(indicators).toHaveProperty('subscription');
  });
});
