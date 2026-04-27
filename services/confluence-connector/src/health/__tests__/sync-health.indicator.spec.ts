import { ConfigService } from '@nestjs/config';
import { HealthIndicatorService } from '@nestjs/terminus';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SyncHealthIndicator } from '../sync-health.indicator';
import type { SyncRecord } from '../sync-result.types';
import { SyncStatusStore } from '../sync-status.store';

const HISTORY_SIZE = 10;
const THRESHOLD = 0.5;

function makeRecord(overrides: Partial<SyncRecord> = {}): SyncRecord {
  return {
    timestamp: new Date('2026-04-27T10:15:00.000Z'),
    tenantName: 'tenant-a',
    result: { status: 'success' },
    ...overrides,
  };
}

const configGetImpl = (stub: CallableFunction) => ({
  ...stub(),
  get: vi.fn((key: string) => {
    if (key === 'health.syncHistorySize') {
      return HISTORY_SIZE;
    }
    if (key === 'health.syncTenantFailureThreshold') {
      return THRESHOLD;
    }
    return undefined;
  }),
});

describe('SyncHealthIndicator', () => {
  let indicator: SyncHealthIndicator;
  let store: SyncStatusStore;

  beforeEach(async () => {
    const storeBed = await TestBed.solitary(SyncStatusStore)
      .mock(ConfigService)
      .impl(configGetImpl)
      .compile();
    store = storeBed.unit;

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

  it('returns up with a message when no sync records exist', () => {
    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: { status: 'up', message: 'No sync records yet' },
    });
  });

  it('returns up when every tenant is below the threshold', () => {
    store.record(makeRecord({ tenantName: 'tenant-a', result: { status: 'success' } }));
    store.record(
      makeRecord({
        tenantName: 'tenant-a',
        result: { status: 'failure' },
      }),
    );
    store.record(makeRecord({ tenantName: 'tenant-b', result: { status: 'success' } }));

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-04-27T10:15:00.000Z',
        tenants: {
          'tenant-a': { failures: 1, total: 2 },
          'tenant-b': { failures: 0, total: 1 },
        },
      },
    });
  });

  it('reports only tenants that have sync records', () => {
    store.record(makeRecord({ tenantName: 'tenant-a', result: { status: 'success' } }));

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-04-27T10:15:00.000Z',
        tenants: {
          'tenant-a': { failures: 0, total: 1 },
        },
      },
    });
  });

  it('returns down when a tenant exceeds the failure threshold', () => {
    // tenant-a: 3/4 failures = 0.75 > 0.5
    store.record(
      makeRecord({
        tenantName: 'tenant-a',
        result: { status: 'failure' },
      }),
    );
    store.record(
      makeRecord({
        tenantName: 'tenant-a',
        result: { status: 'failure' },
      }),
    );
    store.record(
      makeRecord({
        tenantName: 'tenant-a',
        result: { status: 'failure' },
      }),
    );
    store.record(makeRecord({ tenantName: 'tenant-a', result: { status: 'success' } }));
    // tenant-b: 0/1 failures = 0 — healthy
    store.record(makeRecord({ tenantName: 'tenant-b', result: { status: 'success' } }));

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'down',
        lastSyncAt: '2026-04-27T10:15:00.000Z',
        threshold: THRESHOLD,
        failingTenants: ['tenant-a'],
        tenants: {
          'tenant-a': { failures: 3, total: 4 },
          'tenant-b': { failures: 0, total: 1 },
        },
      },
    });
  });

  it('treats skipped runs as part of total but not as failures', () => {
    // 1 success, 1 skipped — failure ratio is 0/2 = 0 (healthy).
    store.record(makeRecord({ result: { status: 'success' } }));
    store.record(makeRecord({ result: { status: 'skipped', reason: 'tenant_idle' } }));

    const result = indicator.check('sync');

    expect(result).toEqual({
      sync: {
        status: 'up',
        lastSyncAt: '2026-04-27T10:15:00.000Z',
        tenants: {
          'tenant-a': { failures: 0, total: 2 },
        },
      },
    });
  });
});
