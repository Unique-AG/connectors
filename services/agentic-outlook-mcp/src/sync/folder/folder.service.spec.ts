/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */

import { TypeID } from 'typeid-js';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MockDrizzleDatabase } from '../__mocks__';
import { DrizzleDatabase } from '../drizzle';

describe('FolderService', () => {
  let mockDb: MockDrizzleDatabase;
  let mockGraphClientFactory: any;
  let service: any;

  const mockUserProfileId = new TypeID('user_profile');

  beforeEach(async () => {
    vi.clearAllMocks();

    mockDb = new MockDrizzleDatabase();
    mockGraphClientFactory = {};

    const { FolderService } = await import('./folder.service');
    service = new FolderService(mockDb as unknown as DrizzleDatabase, mockGraphClientFactory);
  });

  describe('saveFolders', () => {
    it('inserts new folders and updates user profile sync time', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: 0,
        },
        {
          id: 'folder-2',
          name: 'Sent Items',
          displayName: 'Sent Items',
          parentFolderId: null,
          childFolderCount: 1,
        },
      ];

      mockDb.__nextQueryFolders = [];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      expect(mockDb.query.folders.findMany).toHaveBeenCalledWith({
        columns: {
          folderId: true,
        },
      });

      expect(mockDb.insert).toHaveBeenCalled();
      const insertBuilder = mockDb.insert.mock.results[0]?.value;
      expect(insertBuilder.values).toHaveBeenCalledWith([
        {
          name: 'Inbox',
          originalName: 'Inbox',
          folderId: 'folder-1',
          parentFolderId: null,
          childFolderCount: 0,
          userProfileId: mockUserProfileId.toString(),
        },
        {
          name: 'Sent Items',
          originalName: 'Sent Items',
          folderId: 'folder-2',
          parentFolderId: null,
          childFolderCount: 1,
          userProfileId: mockUserProfileId.toString(),
        },
      ]);
      expect(insertBuilder.onConflictDoUpdate).toHaveBeenCalled();

      expect(mockDb.update).toHaveBeenCalled();
      const updateBuilder = mockDb.update.mock.results[0]?.value;
      expect(updateBuilder.set).toHaveBeenCalledWith(
        expect.objectContaining({
          syncLastSyncedAt: expect.any(String),
        }),
      );
      expect(updateBuilder.where).toHaveBeenCalled();
    });

    it('deletes folders that no longer exist', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: 0,
        },
      ];

      mockDb.__nextQueryFolders = [
        { folderId: 'folder-1' },
        { folderId: 'folder-2' },
        { folderId: 'folder-3' },
      ];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      expect(mockDb.delete).toHaveBeenCalled();
      const deleteBuilder = mockDb.delete.mock.results[0]?.value;
      expect(deleteBuilder.where).toHaveBeenCalled();
    });

    it('does not call delete when no folders need to be deleted', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: 0,
        },
      ];

      mockDb.__nextQueryFolders = [{ folderId: 'folder-1' }];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      expect(mockDb.delete).not.toHaveBeenCalled();
    });

    it('filters out folders without id before inserting', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: 0,
        },
        {
          id: null,
          name: 'Invalid Folder',
          displayName: 'Invalid Folder',
          parentFolderId: null,
          childFolderCount: 0,
        },
        {
          id: undefined,
          name: 'Another Invalid',
          displayName: 'Another Invalid',
          parentFolderId: null,
          childFolderCount: 0,
        },
      ];

      mockDb.__nextQueryFolders = [];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      const insertBuilder = mockDb.insert.mock.results[0]?.value;
      expect(insertBuilder.values).toHaveBeenCalledWith([
        {
          name: 'Inbox',
          originalName: 'Inbox',
          folderId: 'folder-1',
          parentFolderId: null,
          childFolderCount: 0,
          userProfileId: mockUserProfileId.toString(),
        },
      ]);
    });

    it('handles folders with nested hierarchy', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: 1,
        },
        {
          id: 'folder-2',
          name: 'Inbox / Archive',
          displayName: 'Archive',
          parentFolderId: 'folder-1',
          childFolderCount: 0,
        },
      ];

      mockDb.__nextQueryFolders = [];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      const insertBuilder = mockDb.insert.mock.results[0]?.value;
      expect(insertBuilder.values).toHaveBeenCalledWith([
        {
          name: 'Inbox',
          originalName: 'Inbox',
          folderId: 'folder-1',
          parentFolderId: null,
          childFolderCount: 1,
          userProfileId: mockUserProfileId.toString(),
        },
        {
          name: 'Inbox / Archive',
          originalName: 'Archive',
          folderId: 'folder-2',
          parentFolderId: 'folder-1',
          childFolderCount: 0,
          userProfileId: mockUserProfileId.toString(),
        },
      ]);
    });

    it('defaults childFolderCount to 0 when null or undefined', async () => {
      const mockFolders = [
        {
          id: 'folder-1',
          name: 'Inbox',
          displayName: 'Inbox',
          parentFolderId: null,
          childFolderCount: null,
        },
        {
          id: 'folder-2',
          name: 'Sent',
          displayName: 'Sent',
          parentFolderId: null,
          childFolderCount: undefined,
        },
      ];

      mockDb.__nextQueryFolders = [];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, mockFolders);

      const insertBuilder = mockDb.insert.mock.results[0]?.value;
      expect(insertBuilder.values).toHaveBeenCalledWith([
        expect.objectContaining({
          folderId: 'folder-1',
          childFolderCount: 0,
        }),
        expect.objectContaining({
          folderId: 'folder-2',
          childFolderCount: 0,
        }),
      ]);
    });

    it('handles empty folder list', async () => {
      mockDb.__nextQueryFolders = [{ folderId: 'folder-1' }, { folderId: 'folder-2' }];

      const saveFolders = service.saveFolders.bind(service);
      await saveFolders(mockUserProfileId, []);

      const insertBuilder = mockDb.insert.mock.results[0]?.value;
      expect(insertBuilder.values).toHaveBeenCalledWith([]);

      expect(mockDb.delete).toHaveBeenCalled();

      expect(mockDb.update).toHaveBeenCalled();
    });
  });
});
