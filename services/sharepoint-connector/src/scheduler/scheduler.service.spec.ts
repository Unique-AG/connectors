import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { SharepointScannerService } from '../sharepoint-scanner/sharepoint-scanner.service';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  it('triggers scan', async () => {
    const runSyncMock = vi.fn().mockResolvedValue(undefined);
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointScannerService)
      .impl(() => ({ runSync: runSyncMock }))
      .compile();
    const svc = unit;
    await svc.runScheduledScan();
    expect(runSyncMock).toHaveBeenCalledTimes(1);
  });
});
