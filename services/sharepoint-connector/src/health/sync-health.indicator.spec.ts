import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FullSyncStep, SiteSyncStep } from '../constants/sync-step.enum';
import { SyncHealthIndicator } from './sync-health.indicator';
import { SyncRecord, SyncStatusStore } from './sync-status.store';

const HISTORY_SIZE = 10;
const THRESHOLD = 0.5;

function makeSyncRecord(overrides: Partial<SyncRecord> = {}): SyncRecord {
  return {
    timestamp: new Date('2026-03-18T10:15:00.000Z'),
    fullResult: { status: 'success' },
    siteResults: [],
    ...overrides,
  };
}

const configGetImpl = (stub: CallableFunction) => ({
  ...stub(),
  get: vi.fn((key: string) => {
    if (key === 'health.syncHistorySize') {
      return HISTORY_SIZE;
    }
    if (key === 'health.syncSiteFailureThreshold') {
      return THRESHOLD;
    }
    return undefined;
  }),
});

describe('SyncHealthIndicator', () => {
  let indicator: SyncHealthIndicator;
  let store: SyncStatusStore;

  beforeEach(async () => {
    const storeTestBed = await TestBed.solitary(SyncStatusStore)
      .mock(ConfigService)
      .impl(configGetImpl)
      .compile();
    store = storeTestBed.unit;

    const { unit } = await TestBed.solitary(SyncHealthIndicator)
      .mock(ConfigService)
      .impl(configGetImpl)
      .mock(SyncStatusStore)
      .final(store)
      .mock(HealthIndicatorService)
      .impl(() => ({
        check: (key: string) => ({
          up: (data?: Record<string, unknown>) => ({ [key]: { status: 'up', ...data } }),
          down: (data?: Record<string, unknown>) => ({ [key]: { status: 'down', ...data } }),
        }),
      }))
      .compile();

    indicator = unit;
  });

  it('returns up with message when no sync records exist', () => {
    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: { status: 'up', message: 'No sync records yet' },
    });
  });

  it('returns up when all sites are below threshold', () => {
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'failure', step: SiteSyncStep.ContentSync } },
        ],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        recentSyncs: 2,
        sites: {
          'site-aaa': { failures: 0, total: 2 },
          'site-bbb': { failures: 1, total: 2 },
        },
      },
    });
  });

  it('returns down when one site exceeds threshold while others are healthy', () => {
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          {
            siteId: 'site-bbb',
            result: { status: 'failure', step: SiteSyncStep.PermissionsFetch },
          },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'failure', step: SiteSyncStep.ContentSync } },
        ],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'down',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        threshold: 0.5,
        failingSites: ['site-bbb'],
        sites: {
          'site-aaa': { failures: 0, total: 2 },
          'site-bbb': { failures: 2, total: 2 },
        },
      },
    });
  });

  it('computes denominator from appearances, not total syncs', () => {
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'failure', step: SiteSyncStep.ContentSync } },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        recentSyncs: 3,
        sites: {
          'site-aaa': { failures: 1, total: 3 },
          'site-bbb': { failures: 0, total: 2 },
        },
      },
    });
  });

  it('counts full sync failure with empty siteResults as failure for all known sites', () => {
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        fullResult: { status: 'failure', step: FullSyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        recentSyncs: 2,
        sites: {
          'site-aaa': { failures: 1, total: 2 },
          'site-bbb': { failures: 1, total: 2 },
        },
      },
    });
  });

  it('reports down when all records are full sync failures with no site data', () => {
    store.record(
      makeSyncRecord({
        fullResult: { status: 'failure', step: FullSyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    );
    store.record(
      makeSyncRecord({
        fullResult: { status: 'failure', step: FullSyncStep.Unknown },
        siteResults: [],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'down',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        threshold: 0.5,
        failingSites: [],
        sites: {},
      },
    });
  });

  it('reports down when full sync failures push known sites over threshold', () => {
    store.record(
      makeSyncRecord({
        siteResults: [{ siteId: 'site-aaa', result: { status: 'success' } }],
      }),
    );
    store.record(
      makeSyncRecord({
        fullResult: { status: 'failure', step: FullSyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    );
    store.record(
      makeSyncRecord({
        fullResult: { status: 'failure', step: FullSyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'down',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        threshold: 0.5,
        failingSites: ['site-aaa'],
        sites: {
          'site-aaa': { failures: 2, total: 3 },
        },
      },
    });
  });

  it('treats exact threshold ratio as healthy (up)', () => {
    store.record(
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'failure', step: SiteSyncStep.ContentSync } },
        ],
      }),
    );
    store.record(
      makeSyncRecord({
        siteResults: [{ siteId: 'site-aaa', result: { status: 'success' } }],
      }),
    );

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-03-18T10:15:00.000Z',
        recentSyncs: 2,
        sites: {
          'site-aaa': { failures: 1, total: 2 },
        },
      },
    });
  });
});
