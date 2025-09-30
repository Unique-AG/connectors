import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { SharepointScannerService } from '../sharepoint-scanner/sharepoint-scanner.service';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  it('triggers scan', async () => {
    const synchronizeMock = vi.fn().mockResolvedValue(undefined);
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointScannerService)
      .impl(() => ({ synchronize: synchronizeMock }))
      .compile();
    const svc = unit;
    await svc.runScheduledScan();
    expect(synchronizeMock).toHaveBeenCalledTimes(1);
  });
});
