import { createMock, type DeepMocked } from '@golevelup/ts-vitest';
import type { INestApplication } from '@nestjs/common';
import { type HealthIndicatorResult, TerminusModule } from '@nestjs/terminus';
import { Test } from '@nestjs/testing';
import request from 'supertest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HealthController } from '../health.controller';
import { MsGraphConnectivityHealthIndicator } from '../ms-graph-connectivity-health.indicator';
import { SyncHealthIndicator } from '../sync-health.indicator';
import { UniqueApiHealthIndicator } from '../unique-api-health.indicator';

const syncUp = {
  sync: {
    status: 'up',
    lastSyncAt: '2026-04-27T10:15:00.000Z',
    tenants: { 'tenant-a': { failures: 0, total: 1 } },
  },
} satisfies HealthIndicatorResult;

const connectivityUp = {
  connectivity: {
    status: 'up',
    atlassian: 'reachable',
    confluence: [{ tenant: 'tenant-a', status: 'reachable' }],
  },
} satisfies HealthIndicatorResult;

const uniqueApiUp = {
  uniqueApi: {
    status: 'up',
    ingestion: [{ tenant: 'tenant-a', status: 'reachable' }],
    scopeManagement: [{ tenant: 'tenant-a', status: 'reachable' }],
  },
} satisfies HealthIndicatorResult;

const syncDown = {
  sync: {
    status: 'down',
    lastSyncAt: '2026-04-27T10:15:00.000Z',
    threshold: 0.5,
    failingTenants: ['tenant-a'],
    tenants: { 'tenant-a': { failures: 3, total: 4 } },
  },
} satisfies HealthIndicatorResult;

describe('HealthController', () => {
  let app: INestApplication;
  let syncIndicator: DeepMocked<SyncHealthIndicator>;
  let connectivityIndicator: DeepMocked<MsGraphConnectivityHealthIndicator>;
  let uniqueApiIndicator: DeepMocked<UniqueApiHealthIndicator>;

  beforeEach(async () => {
    syncIndicator = createMock<SyncHealthIndicator>({
      check: vi.fn(() => syncUp),
    });
    connectivityIndicator = createMock<MsGraphConnectivityHealthIndicator>({
      check: vi.fn(() => Promise.resolve(connectivityUp)),
    });
    uniqueApiIndicator = createMock<UniqueApiHealthIndicator>({
      check: vi.fn(() => Promise.resolve(uniqueApiUp)),
    });

    const moduleRef = await Test.createTestingModule({
      imports: [TerminusModule],
      controllers: [HealthController],
      providers: [
        { provide: SyncHealthIndicator, useValue: syncIndicator },
        { provide: MsGraphConnectivityHealthIndicator, useValue: connectivityIndicator },
        { provide: UniqueApiHealthIndicator, useValue: uniqueApiIndicator },
      ],
    }).compile();

    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterEach(async () => {
    await app.close();
  });

  it('returns 200 with all indicator details when every check is up', async () => {
    const response = await request(app.getHttpServer()).get('/health').expect(200);

    expect(response.body).toEqual({
      status: 'ok',
      info: {
        ...syncUp,
        ...connectivityUp,
        ...uniqueApiUp,
      },
      error: {},
      details: {
        ...syncUp,
        ...connectivityUp,
        ...uniqueApiUp,
      },
    });
    expect(syncIndicator.check).toHaveBeenCalledWith('sync');
    expect(connectivityIndicator.check).toHaveBeenCalledWith('connectivity');
    expect(uniqueApiIndicator.check).toHaveBeenCalledWith('uniqueApi');
  });

  it('returns 503 with the failed indicator in error and details', async () => {
    vi.mocked(syncIndicator.check).mockReturnValueOnce(syncDown);

    const response = await request(app.getHttpServer()).get('/health').expect(503);

    expect(response.body).toEqual({
      status: 'error',
      info: {
        ...connectivityUp,
        ...uniqueApiUp,
      },
      error: syncDown,
      details: {
        ...syncDown,
        ...connectivityUp,
        ...uniqueApiUp,
      },
    });
  });
});
