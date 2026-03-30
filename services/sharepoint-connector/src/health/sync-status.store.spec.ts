import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SyncStep } from '../constants/sync-step.enum';
import { FullSyncResult, SyncRecord, SyncStatusStore } from './sync-status.store';

const HISTORY_SIZE = 3;

function makeSyncRecord(overrides: Partial<SyncRecord> = {}): SyncRecord {
  return {
    timestamp: new Date(),
    fullResult: { status: 'success' },
    siteResults: [],
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
    it('returns an empty array when no records exist', () => {
      expect(store.getRecords()).toEqual([]);
    });

    it('returns undefined for latest when no records exist', () => {
      expect(store.getLatest()).toBeUndefined();
    });
  });

  describe('record()', () => {
    it('stores a single sync record', () => {
      const record = makeSyncRecord();
      store.record(record);

      expect(store.getRecords()).toEqual([record]);
    });

    it('preserves insertion order', () => {
      const first = makeSyncRecord({ timestamp: new Date('2025-01-01') });
      const second = makeSyncRecord({ timestamp: new Date('2025-01-02') });
      const third = makeSyncRecord({ timestamp: new Date('2025-01-03') });

      store.record(first);
      store.record(second);
      store.record(third);

      expect(store.getRecords()).toEqual([first, second, third]);
    });

    it('drops the oldest record when buffer is full', () => {
      const records = Array.from({ length: 4 }, (_, i) =>
        makeSyncRecord({ timestamp: new Date(`2025-01-0${i + 1}`) }),
      );

      for (const r of records) store.record(r);

      expect(store.getRecords()).toHaveLength(HISTORY_SIZE);
      expect(store.getRecords()).toEqual(records.slice(1));
    });

    it('never exceeds configured max size after many inserts', () => {
      for (let i = 0; i < 10; i++) {
        store.record(makeSyncRecord());
      }
      expect(store.getRecords()).toHaveLength(HISTORY_SIZE);
    });

    it('stores records with site-level failure details', () => {
      const record = makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.ContentSync },
        siteResults: [
          { siteId: 'site-1', result: { status: 'success' } },
          { siteId: 'site-2', result: { status: 'failure', step: SyncStep.PermissionsSync } },
          { siteId: 'site-3', result: { status: 'skipped', reason: 'not configured' } },
        ],
      });

      store.record(record);

      const stored = store.getLatest()!;
      expect(stored.fullResult).toEqual({ status: 'failure', step: SyncStep.ContentSync });
      expect(stored.siteResults).toHaveLength(3);
      expect(stored.siteResults[1].result).toEqual({
        status: 'failure',
        step: SyncStep.PermissionsSync,
      });
    });
  });

  describe('getLatest()', () => {
    it('returns the most recently recorded entry', () => {
      const first = makeSyncRecord({ fullResult: { status: 'success' } });
      const second = makeSyncRecord({
        fullResult: { status: 'failure', step: SyncStep.Unknown },
      });

      store.record(first);
      store.record(second);

      expect(store.getLatest()).toBe(second);
    });

    it('returns the newest record after overflow', () => {
      const records = Array.from({ length: 5 }, (_, i) =>
        makeSyncRecord({
          fullResult: { status: 'skipped', reason: `reason-${i}` } satisfies FullSyncResult,
        }),
      );

      for (const r of records) store.record(r);

      expect(store.getLatest()).toBe(records[4]);
    });
  });
});
