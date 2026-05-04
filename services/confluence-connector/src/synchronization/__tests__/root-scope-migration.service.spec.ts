import type { UniqueApiClient } from '@unique-ag/unique-api';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { RootScopeMigrationService } from '../root-scope-migration.service';

const NEW_ROOT_ID = 'new-root-scope-id';
const OLD_ROOT_ID = 'old-root-scope-id';
const EXTERNAL_ID = 'confc:cloud:cloud-abc-123';

interface MockDeps {
  service: RootScopeMigrationService;
  scopes: {
    getByExternalId: ReturnType<typeof vi.fn>;
    listChildren: ReturnType<typeof vi.fn>;
    updateParent: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
}

function makeService(): MockDeps {
  const scopes = {
    getByExternalId: vi.fn(),
    listChildren: vi.fn(),
    updateParent: vi.fn().mockResolvedValue(undefined),
    delete: vi.fn().mockResolvedValue({ successFolders: [], failedFolders: [] }),
  };

  const uniqueApiClient = { scopes } as unknown as UniqueApiClient;

  return {
    service: new RootScopeMigrationService(uniqueApiClient),
    scopes,
  };
}

describe('RootScopeMigrationService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('migrateIfNeeded', () => {
    it('returns no_migration_needed when getByExternalId returns null', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue(null);

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({ status: 'no_migration_needed' });
      expect(scopes.listChildren).not.toHaveBeenCalled();
      expect(scopes.updateParent).not.toHaveBeenCalled();
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('returns no_migration_needed when old root id equals new root id', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: NEW_ROOT_ID,
        name: 'Confluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({ status: 'no_migration_needed' });
      expect(scopes.listChildren).not.toHaveBeenCalled();
    });

    it('migrates multiple children and deletes old root', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'Space1', parentId: OLD_ROOT_ID },
        { id: 'child-2', name: 'Space2', parentId: OLD_ROOT_ID },
        { id: 'child-3', name: 'Space3', parentId: OLD_ROOT_ID },
      ]);
      scopes.delete.mockResolvedValue({ successFolders: [{ id: OLD_ROOT_ID }], failedFolders: [] });

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({ status: 'migration_completed' });
      expect(scopes.updateParent).toHaveBeenCalledTimes(3);
      expect(scopes.updateParent).toHaveBeenCalledWith('child-1', NEW_ROOT_ID);
      expect(scopes.updateParent).toHaveBeenCalledWith('child-2', NEW_ROOT_ID);
      expect(scopes.updateParent).toHaveBeenCalledWith('child-3', NEW_ROOT_ID);
      expect(scopes.delete).toHaveBeenCalledWith(OLD_ROOT_ID);
    });

    it('skips updateParent when no children and still deletes old root', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([]);
      scopes.delete.mockResolvedValue({ successFolders: [{ id: OLD_ROOT_ID }], failedFolders: [] });

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({ status: 'migration_completed' });
      expect(scopes.updateParent).not.toHaveBeenCalled();
      expect(scopes.delete).toHaveBeenCalledWith(OLD_ROOT_ID);
    });

    it('returns migration_failed with count when one of three updateParent calls rejects', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'Space1', parentId: OLD_ROOT_ID },
        { id: 'child-2', name: 'Space2', parentId: OLD_ROOT_ID },
        { id: 'child-3', name: 'Space3', parentId: OLD_ROOT_ID },
      ]);
      scopes.updateParent
        .mockResolvedValueOnce(undefined)
        .mockRejectedValueOnce(new Error('reparent failed'))
        .mockResolvedValueOnce(undefined);

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: expect.stringContaining('1 of 3'),
      });
      expect(result).toEqual({
        status: 'migration_failed',
        error: expect.stringContaining('reparent failed'),
      });
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('returns migration_failed with N of N when all children fail', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'Space1', parentId: OLD_ROOT_ID },
        { id: 'child-2', name: 'Space2', parentId: OLD_ROOT_ID },
      ]);
      scopes.updateParent.mockRejectedValue(new Error('all broken'));

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: expect.stringContaining('2 of 2'),
      });
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('returns migration_failed when delete returns failed folders', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([]);
      scopes.delete.mockResolvedValue({
        successFolders: [],
        failedFolders: [
          {
            id: OLD_ROOT_ID,
            name: 'OldConfluence',
            path: '/OldConfluence',
            failReason: 'not empty',
          },
        ],
      });

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: 'Failed to delete old root scope',
      });
    });

    it('returns migration_failed when getByExternalId throws', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockRejectedValue(new Error('Network error'));

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: 'Network error',
      });
    });

    it('returns migration_failed when listChildren throws', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockRejectedValue(new Error('Failed to list children'));

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: 'Failed to list children',
      });
    });

    it('returns migration_failed when delete throws', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([]);
      scopes.delete.mockRejectedValue(new Error('Delete operation failed'));

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: 'Delete operation failed',
      });
    });

    it('converts non-Error rejection to string in error result', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockRejectedValue('string error');

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: 'string error',
      });
    });

    it('converts non-Error thrown from updateParent to string in error result', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValue({
        id: OLD_ROOT_ID,
        name: 'OldConfluence',
        parentId: null,
        externalId: EXTERNAL_ID,
      });
      scopes.listChildren.mockResolvedValue([
        { id: 'child-1', name: 'Space1', parentId: OLD_ROOT_ID },
      ]);
      scopes.updateParent.mockRejectedValue('string reparent error');

      const result = await service.migrateIfNeeded(NEW_ROOT_ID, EXTERNAL_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        error: expect.stringContaining('string reparent error'),
      });
      expect(scopes.delete).not.toHaveBeenCalled();
    });
  });
});
