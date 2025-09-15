import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { SharepointScannerService } from '../sharepoint-scanner/sharepoint-scanner.service';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  it('triggers scan', async () => {
    const { unit, unitRef } = await TestBed.solitary(SchedulerService)
      .mock(SharepointScannerService)
      .impl(() => ({ scanForWork: vi.fn().mockResolvedValue(undefined) }))
      .compile();
    const svc = unit;
    const scanner = unitRef.get(SharepointScannerService);
    await svc.runScheduledScan();
    expect((scanner.scanForWork as any).mock.calls.length).toBe(1);
  });
});
