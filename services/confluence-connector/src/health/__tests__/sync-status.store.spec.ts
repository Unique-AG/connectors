import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { type SyncRecord, SyncStep } from '../sync-result.types';
import { SyncStatusStore } from '../sync-status.store';

const HISTORY_SIZE = 3;

function makeRecord(overrides: Partial<SyncRecord> = {}): SyncRecord {
  return {
    timestamp: new Date(),
    tenantName: 'tenant-a',
    result: { status: 'success' },
    ...overrides,
  };
}

describe('SyncStatusStore', () => {
  let store: SyncStatusStore;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(SyncStatusStore)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn(() => HISTORY_SIZE),
      }))
      .compile();
    store = unit;
  });

  describe('empty state', () => {
    it('returns an empty map when no records exist', () => {
      expect(store.getRecordsByTenant().size).toBe(0);
    });

    it('returns undefined for latest when no records exist', () => {
      expect(store.getLatest()).toBeUndefined();
    });
  });

  describe('record()', () => {
    it('stores a record under its tenant name', () => {
      const record = makeRecord({ tenantName: 'tenant-a' });
      store.record(record);

      const records = store.getRecordsByTenant();
      expect(records.get('tenant-a')).toEqual([record]);
    });

    it('keeps separate ring buffers per tenant', () => {
      const aRecord = makeRecord({ tenantName: 'tenant-a' });
      const bRecord = makeRecord({ tenantName: 'tenant-b' });

      store.record(aRecord);
      store.record(bRecord);

      const records = store.getRecordsByTenant();
      expect(records.get('tenant-a')).toEqual([aRecord]);
      expect(records.get('tenant-b')).toEqual([bRecord]);
    });

    it('drops the oldest record per tenant when its ring buffer is full', () => {
      const records = Array.from({ length: 4 }, (_, i) =>
        makeRecord({
          tenantName: 'tenant-a',
          timestamp: new Date(`2026-01-0${i + 1}`),
        }),
      );

      for (const r of records) {
        store.record(r);
      }

      const stored = store.getRecordsByTenant().get('tenant-a') ?? [];
      expect(stored).toHaveLength(HISTORY_SIZE);
      expect(stored).toEqual(records.slice(1));
    });

    it('never exceeds configured max size for one tenant after many inserts', () => {
      for (let i = 0; i < 10; i++) {
        store.record(makeRecord({ tenantName: 'tenant-a' }));
      }
      expect(store.getRecordsByTenant().get('tenant-a')).toHaveLength(HISTORY_SIZE);
    });

    it('stores failure step on the record', () => {
      const record = makeRecord({
        result: { status: 'failure', step: SyncStep.PageIngestion },
      });
      store.record(record);

      const stored = store.getRecordsByTenant().get('tenant-a')?.[0];
      expect(stored?.result).toEqual({ status: 'failure', step: SyncStep.PageIngestion });
    });
  });

  describe('getLatest()', () => {
    it('returns the most recently recorded entry across all tenants', () => {
      const aOlder = makeRecord({
        tenantName: 'tenant-a',
        timestamp: new Date('2026-01-01T00:00:00.000Z'),
      });
      const bNewer = makeRecord({
        tenantName: 'tenant-b',
        timestamp: new Date('2026-01-02T00:00:00.000Z'),
      });

      store.record(aOlder);
      store.record(bNewer);

      expect(store.getLatest()).toBe(bNewer);
    });

    it('returns the newest record for a tenant after its buffer overflows', () => {
      const records = Array.from({ length: 5 }, (_, i) =>
        makeRecord({
          tenantName: 'tenant-a',
          timestamp: new Date(`2026-01-0${i + 1}T00:00:00.000Z`),
        }),
      );
      for (const r of records) {
        store.record(r);
      }

      expect(store.getLatest()).toBe(records[4]);
    });
  });
});
