import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { SyncStatusStore } from '../health/sync-status.store';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  it('triggers scan and records result', async () => {
    const synchronizeMock = vi.fn().mockResolvedValue({
      fullResult: { status: 'success' },
      siteResults: [{ siteId: 'site-1', result: { status: 'success' } }],
    });
    const recordMock = vi.fn();
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointSynchronizationService)
      .impl(() => ({ synchronize: synchronizeMock }))
      .mock(SyncStatusStore)
      .impl(() => ({ record: recordMock }))
      .compile();

    await unit.runScheduledScan();

    expect(synchronizeMock).toHaveBeenCalledTimes(1);
    expect(recordMock).toHaveBeenCalledWith(
      expect.objectContaining({
        fullResult: { status: 'success' },
        siteResults: [{ siteId: 'site-1', result: { status: 'success' } }],
      }),
    );
  });

  it('does not record when scan is skipped due to scan_in_progress', async () => {
    const synchronizeMock = vi.fn().mockResolvedValue({
      fullResult: { status: 'skipped', reason: 'scan_in_progress' },
      siteResults: [],
    });
    const recordMock = vi.fn();
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointSynchronizationService)
      .impl(() => ({ synchronize: synchronizeMock }))
      .mock(SyncStatusStore)
      .impl(() => ({ record: recordMock }))
      .compile();

    await unit.runScheduledScan();

    expect(synchronizeMock).toHaveBeenCalledTimes(1);
    expect(recordMock).not.toHaveBeenCalled();
  });

  it('records failure on unexpected error', async () => {
    const synchronizeMock = vi.fn().mockRejectedValue(new Error('boom'));
    const recordMock = vi.fn();
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointSynchronizationService)
      .impl(() => ({ synchronize: synchronizeMock }))
      .mock(SyncStatusStore)
      .impl(() => ({ record: recordMock }))
      .compile();

    await unit.runScheduledScan();

    expect(recordMock).toHaveBeenCalledWith(
      expect.objectContaining({
        fullResult: { status: 'failure', step: 'unknown' },
        siteResults: [],
      }),
    );
  });
});
