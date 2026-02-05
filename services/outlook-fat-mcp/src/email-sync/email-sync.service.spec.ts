import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TypeID } from 'typeid-js';
import { typeid } from 'typeid-js';
import { EmailSyncService } from './email-sync.service';

const mockDb = {
  query: {
    emailSyncConfigs: {
      findFirst: vi.fn(),
      findMany: vi.fn(),
    },
    emailSyncMessages: {
      findFirst: vi.fn(),
      findMany: vi.fn(),
    },
    userProfiles: {
      findFirst: vi.fn(),
    },
  },
  insert: vi.fn(() => ({
    values: vi.fn(() => ({
      returning: vi.fn(),
    })),
  })),
  update: vi.fn(() => ({
    set: vi.fn(() => ({
      where: vi.fn(() => ({
        returning: vi.fn(),
      })),
    })),
  })),
  $count: vi.fn(),
};

const mockGraphClientFactory = {
  createClientForUser: vi.fn(),
};

const mockUniqueService = {
  ingestEmail: vi.fn(),
};

const mockConfig = {
  get: vi.fn((key: string) => {
    const config: Record<string, unknown> = {
      'emailSync.batchSize': 50,
      'emailSync.syncIntervalCron': '0 */15 * * * *',
      'emailSync.enabled': true,
    };
    return config[key];
  }),
};

const mockTrace = {
  getSpan: vi.fn(() => ({
    setAttribute: vi.fn(),
    addEvent: vi.fn(),
  })),
};

describe('EmailSyncService', () => {
  let service: EmailSyncService;
  let userProfileId: TypeID<'user_profile'>;

  beforeEach(() => {
    vi.clearAllMocks();
    userProfileId = typeid('user_profile');

    // biome-ignore lint/suspicious/noExplicitAny: Test mock
    service = new EmailSyncService(
      mockDb as any,
      mockGraphClientFactory as any,
      mockUniqueService as any,
      mockConfig as any,
      mockTrace as any,
    );
  });

  describe('startSync', () => {
    const syncFromDate = new Date('2024-01-01');

    it('creates new sync config when none exists', async () => {
      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(null);

      const newConfig = {
        id: 'email_sync_123',
        userProfileId: userProfileId.toString(),
        status: 'active',
        syncFromDate,
        createdAt: new Date(),
        updatedAt: new Date(),
        deltaToken: null,
        nextLink: null,
        lastSyncAt: null,
        lastError: null,
      };

      mockDb.insert.mockReturnValue({
        values: vi.fn().mockReturnValue({
          returning: vi.fn().mockResolvedValue([newConfig]),
        }),
      });

      const result = await service.startSync(userProfileId, syncFromDate);

      expect(result.status).toBe('created');
      expect(result.config).toEqual(newConfig);
    });

    it('returns already_active when sync is already active', async () => {
      const existingConfig = {
        id: 'email_sync_123',
        userProfileId: userProfileId.toString(),
        status: 'active',
        syncFromDate,
        createdAt: new Date(),
        updatedAt: new Date(),
        deltaToken: null,
        nextLink: null,
        lastSyncAt: null,
        lastError: null,
      };

      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(existingConfig);

      const result = await service.startSync(userProfileId, syncFromDate);

      expect(result.status).toBe('already_active');
      expect(result.config).toEqual(existingConfig);
    });

    it('resumes stopped sync config', async () => {
      const stoppedConfig = {
        id: 'email_sync_123',
        userProfileId: userProfileId.toString(),
        status: 'stopped',
        syncFromDate,
        createdAt: new Date(),
        updatedAt: new Date(),
        deltaToken: null,
        nextLink: null,
        lastSyncAt: null,
        lastError: null,
      };

      const resumedConfig = { ...stoppedConfig, status: 'active' };

      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(stoppedConfig);
      mockDb.update.mockReturnValue({
        set: vi.fn().mockReturnValue({
          where: vi.fn().mockReturnValue({
            returning: vi.fn().mockResolvedValue([resumedConfig]),
          }),
        }),
      });

      const result = await service.startSync(userProfileId, syncFromDate);

      expect(result.status).toBe('resumed');
      expect(result.config.status).toBe('active');
    });
  });

  describe('getSyncStatus', () => {
    it('returns not_found when no config exists', async () => {
      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(null);

      const result = await service.getSyncStatus(userProfileId);

      expect(result.status).toBe('not_found');
      expect(result.config).toBeUndefined();
    });

    it('returns sync status with message count', async () => {
      const existingConfig = {
        id: 'email_sync_123',
        userProfileId: userProfileId.toString(),
        status: 'active',
        syncFromDate: new Date('2024-01-01'),
        createdAt: new Date(),
        updatedAt: new Date(),
        deltaToken: null,
        nextLink: null,
        lastSyncAt: new Date(),
        lastError: null,
      };

      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(existingConfig);
      mockDb.$count.mockResolvedValue(42);

      const result = await service.getSyncStatus(userProfileId);

      expect(result.status).toBe('active');
      expect(result.config).toEqual(existingConfig);
      expect(result.messageCount).toBe(42);
    });
  });

  describe('stopSync', () => {
    it('returns not_found when no config exists', async () => {
      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(null);

      const result = await service.stopSync(userProfileId);

      expect(result.status).toBe('not_found');
    });

    it('stops an active sync config', async () => {
      const activeConfig = {
        id: 'email_sync_123',
        userProfileId: userProfileId.toString(),
        status: 'active',
        syncFromDate: new Date('2024-01-01'),
        createdAt: new Date(),
        updatedAt: new Date(),
        deltaToken: null,
        nextLink: null,
        lastSyncAt: null,
        lastError: null,
      };

      mockDb.query.emailSyncConfigs.findFirst.mockResolvedValue(activeConfig);
      mockDb.update.mockReturnValue({
        set: vi.fn().mockReturnValue({
          where: vi.fn().mockResolvedValue(undefined),
        }),
      });

      const result = await service.stopSync(userProfileId);

      expect(result.status).toBe('stopped');
    });
  });

  describe('getActiveConfigs', () => {
    it('returns all active configs', async () => {
      const activeConfigs = [
        {
          id: 'email_sync_1',
          userProfileId: 'user_profile_1',
          status: 'active',
          syncFromDate: new Date('2024-01-01'),
          createdAt: new Date(),
          updatedAt: new Date(),
          deltaToken: null,
          nextLink: null,
          lastSyncAt: null,
          lastError: null,
        },
        {
          id: 'email_sync_2',
          userProfileId: 'user_profile_2',
          status: 'active',
          syncFromDate: new Date('2024-02-01'),
          createdAt: new Date(),
          updatedAt: new Date(),
          deltaToken: 'token123',
          nextLink: null,
          lastSyncAt: new Date(),
          lastError: null,
        },
      ];

      mockDb.query.emailSyncConfigs.findMany.mockResolvedValue(activeConfigs);

      const result = await service.getActiveConfigs();

      expect(result).toHaveLength(2);
      expect(result[0].id).toBe('email_sync_1');
      expect(result[1].id).toBe('email_sync_2');
    });
  });
});
