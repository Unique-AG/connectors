import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  it('triggers scan', async () => {
    const synchronizeMock = vi.fn().mockResolvedValue(undefined);
    const { unit } = await TestBed.solitary(SchedulerService)
      .mock(SharepointSynchronizationService)
      .impl(() => ({ synchronize: synchronizeMock }))
      .compile();
    const svc = unit;
    await svc.runScheduledScan();
    expect(synchronizeMock).toHaveBeenCalledTimes(1);
  });
});
