import type { SchedulerRegistry } from '@nestjs/schedule';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SearchCursorRepository } from '../search-cursor.repository';
import { SearchCursorCleanupSchedulerService } from '../search-cursor-cleanup-scheduler.service';

describe(SearchCursorCleanupSchedulerService.name, () => {
  const now = new Date('2026-10-09T03:00:00Z');

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('deletes cursors created more than 30 days ago', async () => {
    const deleteCreatedBefore = vi.fn().mockResolvedValue(3);
    const service = new SearchCursorCleanupSchedulerService(
      {} as SchedulerRegistry,
      { deleteCreatedBefore } as unknown as SearchCursorRepository,
    );

    await service.runCleanup();

    expect(deleteCreatedBefore).toHaveBeenCalledWith(new Date('2026-09-09T03:00:00Z'));
  });

  it('skips the cleanup once the service is shutting down', async () => {
    const deleteCreatedBefore = vi.fn();
    const service = new SearchCursorCleanupSchedulerService(
      { getCronJob: vi.fn().mockReturnValue({ stop: vi.fn() }) } as unknown as SchedulerRegistry,
      { deleteCreatedBefore } as unknown as SearchCursorRepository,
    );

    service.onModuleDestroy();
    await service.runCleanup();

    expect(deleteCreatedBefore).not.toHaveBeenCalled();
  });
});
