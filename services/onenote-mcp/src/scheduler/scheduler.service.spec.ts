import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SchedulerService } from './scheduler.service';

describe('SchedulerService', () => {
  const mockConfig = {
    get: vi.fn((key: string) => {
      const values: Record<string, unknown> = {
        'sync.intervalCron': '*/15 * * * *',
        'sync.concurrency': 2,
      };
      return values[key];
    }),
  };

  const mockSyncService = {
    getAllUserProfileIds: vi.fn(),
    syncUser: vi.fn(),
  };

  let service: SchedulerService;

  beforeEach(() => {
    vi.clearAllMocks();
    // biome-ignore lint/suspicious/noExplicitAny: Test mock
    service = new SchedulerService(mockConfig as any, mockSyncService as any);
  });

  describe('onModuleInit', () => {
    it('initializes the cron job', () => {
      service.onModuleInit();

      expect(mockConfig.get).toHaveBeenCalledWith('sync.intervalCron', { infer: true });
    });
  });

  describe('onModuleDestroy', () => {
    it('stops the cron job', () => {
      service.onModuleInit();
      service.onModuleDestroy();
    });
  });
});
