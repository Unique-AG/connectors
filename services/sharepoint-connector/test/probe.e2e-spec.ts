import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { AppModule } from '../src/app.module';
import { SchedulerService } from '../src/scheduler/scheduler.service';

describe('Probe endpoint (e2e)', () => {
  let app: INestApplication;

  beforeEach(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    })
      .overrideProvider(SchedulerService)
      .useValue({
        onModuleInit: () => {},
        onModuleDestroy: () => {},
      })
      .compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterEach(async () => {
    if (app) {
      await app.close();
    }
  });

  it('/probe (GET) returns health status', async () => {
    const res = await request(app.getHttpServer()).get('/probe').expect(200);
    expect(res.body).toEqual({ version: expect.any(String) });
  });
});
