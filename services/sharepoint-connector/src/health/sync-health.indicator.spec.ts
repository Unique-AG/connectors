import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SyncStep } from '../constants/sync-step.enum';
import { SyncHealthIndicator } from './sync-health.indicator';
import { SyncRecord, SyncStatusStore } from './sync-status.store';

const THRESHOLD = 0.5;

function makeSyncRecord(overrides: Partial<SyncRecord> = {}): SyncRecord {
  return {
    timestamp: new Date('2026-03-18T10:15:00.000Z'),
    fullResult: { status: 'success' },
    siteResults: [],
    ...overrides,
  };
}

describe('SyncHealthIndicator', () => {
  let indicator: SyncHealthIndicator;
  let store: SyncStatusStore;

  beforeEach(async () => {
    const { unit, unitRef } = await TestBed.solitary(SyncHealthIndicator)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn(() => THRESHOLD),
      }))
      .mock(SyncStatusStore)
      .impl((stub) => ({
        ...stub(),
        getRecords: vi.fn(() => []),
        getLatest: vi.fn(() => undefined),
      }))
      .mock(HealthIndicatorService)
      .impl(() => ({
        check: (key: string) => ({
          up: (data?: Record<string, unknown>) => ({ [key]: { status: 'up', ...data } }),
          down: (data?: Record<string, unknown>) => ({ [key]: { status: 'down', ...data } }),
        }),
      }))
      .compile();

    indicator = unit;
    store = unitRef.get(SyncStatusStore);
  });

  it('returns empty object when no sync records exist', () => {
    const result = indicator.check('sync');

    expect(result).toEqual({});
  });

  it('returns up when all sites are below threshold', () => {
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'failure', step: SyncStep.ContentSync } },
        ],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[1]);

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
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'failure', step: SyncStep.PermissionsSync } },
        ],
      }),
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'failure', step: SyncStep.ContentSync } },
        ],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[1]);

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
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'failure', step: SyncStep.ContentSync } },
        ],
      }),
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[2]);

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
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
          { siteId: 'site-bbb', result: { status: 'success' } },
        ],
      }),
      makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[1]);

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
    const records = [
      makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.SitesConfigLoading },
        siteResults: [],
      }),
      makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.Unknown },
        siteResults: [],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[1]);

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
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
        ],
      }),
      makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.SitesConfigLoading },
        siteResults: [],
      }),
      makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.SitesConfigLoading },
        siteResults: [],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[2]);

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
    const records = [
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'failure', step: SyncStep.ContentSync } },
        ],
      }),
      makeSyncRecord({
        siteResults: [
          { siteId: 'site-aaa', result: { status: 'success' } },
        ],
      }),
    ];
    vi.mocked(store.getRecords).mockReturnValue(records);
    vi.mocked(store.getLatest).mockReturnValue(records[1]);

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
