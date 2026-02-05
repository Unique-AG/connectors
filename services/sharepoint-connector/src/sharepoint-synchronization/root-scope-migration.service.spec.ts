import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Config } from '../config';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { Smeared } from '../utils/smeared';
import { RootScopeMigrationService } from './root-scope-migration.service';

describe('RootScopeMigrationService', () => {
  type ConfigServiceMock = ConfigService<Config, true> & { get: ReturnType<typeof vi.fn> };

  let service: RootScopeMigrationService;
  let getScopeByExternalIdMock: ReturnType<typeof vi.fn>;
  let listChildrenScopesMock: ReturnType<typeof vi.fn>;
  let updateScopeParentMock: ReturnType<typeof vi.fn>;
  let deleteScopeRecursivelyMock: ReturnType<typeof vi.fn>;
  let configServiceMock: ConfigServiceMock;

  beforeEach(async () => {
    getScopeByExternalIdMock = vi.fn();
    listChildrenScopesMock = vi.fn();
    updateScopeParentMock = vi.fn();
    deleteScopeRecursivelyMock = vi.fn();

    configServiceMock = {
      get: vi.fn((key: string) => {
        if (key === 'app.logsDiagnosticsDataPolicy') {
          return 'show';
        }
        return undefined;
      }),
    } as unknown as ConfigServiceMock;

    const { unit } = await TestBed.solitary(RootScopeMigrationService)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeByExternalId: getScopeByExternalIdMock,
        listChildrenScopes: listChildrenScopesMock,
        updateScopeParent: updateScopeParentMock,
        deleteScopeRecursively: deleteScopeRecursivelyMock,
      }))
      .mock<ConfigService<Config, true>>(ConfigService)
      .impl(() => configServiceMock)
      .compile();

    service = unit;

    Object.defineProperty(service, 'logger', {
      value: {
        log: vi.fn(),
        error: vi.fn(),
        warn: vi.fn(),
        debug: vi.fn(),
        verbose: vi.fn(),
      },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('migrateIfNeeded', () => {
    describe('migration detection', () => {
      it('returns no_migration_needed when no old root exists', async () => {
        getScopeByExternalIdMock.mockResolvedValue(null);

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'no_migration_needed' });
        expect(getScopeByExternalIdMock).toHaveBeenCalledWith('spc:site:site-456');
        expect(listChildrenScopesMock).not.toHaveBeenCalled();
      });

      it('returns no_migration_needed when old root is same as new root', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'same-root-123',
          name: 'SiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });

        const result = await service.migrateIfNeeded(
          'same-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'no_migration_needed' });
        expect(listChildrenScopesMock).not.toHaveBeenCalled();
      });

      it('triggers migration when old root exists with different id', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Child1', parentId: 'old-root-123' },
        ]);
        updateScopeParentMock.mockResolvedValue({ id: 'child-1', parentId: 'new-root-123' });
        deleteScopeRecursivelyMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(listChildrenScopesMock).toHaveBeenCalledWith('old-root-123');
      });
    });

    describe('migration execution', () => {
      it('moves all child scopes to new root and deletes old root', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Folder1', parentId: 'old-root-123' },
          { id: 'child-2', name: 'Folder2', parentId: 'old-root-123' },
          { id: 'child-3', name: 'Folder3', parentId: 'old-root-123' },
        ]);
        updateScopeParentMock.mockResolvedValue({ id: 'child-id', parentId: 'new-root-123' });
        deleteScopeRecursivelyMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(updateScopeParentMock).toHaveBeenCalledTimes(3);
        expect(updateScopeParentMock).toHaveBeenCalledWith('child-1', 'new-root-123');
        expect(updateScopeParentMock).toHaveBeenCalledWith('child-2', 'new-root-123');
        expect(updateScopeParentMock).toHaveBeenCalledWith('child-3', 'new-root-123');
        expect(deleteScopeRecursivelyMock).toHaveBeenCalledWith('old-root-123');
      });

      it('deletes empty old root when no children exist (partial migration resume)', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeRecursivelyMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(updateScopeParentMock).not.toHaveBeenCalled();
        expect(deleteScopeRecursivelyMock).toHaveBeenCalledWith('old-root-123');
      });

      it('logs warning when old root deletion also removes leftover children', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeRecursivelyMock.mockResolvedValue({
          successFolders: [
            { id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' },
            { id: 'leftover-child', name: 'LeftoverChild', path: '/OldSiteRoot/LeftoverChild' },
          ],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
        expect(service['logger'].warn).toHaveBeenCalledWith(
          expect.stringContaining('Successfully deleted old root scope and 1 child folders'),
        );
      });
    });

    describe('error handling', () => {
      it('returns migration_failed when child scope move fails', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Folder1', parentId: 'old-root-123' },
          { id: 'child-2', name: 'Folder2', parentId: 'old-root-123' },
        ]);
        updateScopeParentMock
          .mockResolvedValueOnce({ id: 'child-1', parentId: 'new-root-123' })
          .mockRejectedValueOnce(new Error('API error'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Failed to move 1/2 child scopes to new root',
        });
        expect(deleteScopeRecursivelyMock).not.toHaveBeenCalled();
      });

      it('attempts to move all children even when some fail', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Folder1', parentId: 'old-root-123' },
          { id: 'child-2', name: 'Folder2', parentId: 'old-root-123' },
          { id: 'child-3', name: 'Folder3', parentId: 'old-root-123' },
        ]);
        updateScopeParentMock
          .mockRejectedValueOnce(new Error('API error'))
          .mockResolvedValueOnce({ id: 'child-2', parentId: 'new-root-123' })
          .mockRejectedValueOnce(new Error('API error'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(updateScopeParentMock).toHaveBeenCalledTimes(3);
        expect(updateScopeParentMock).toHaveBeenNthCalledWith(1, 'child-1', 'new-root-123');
        expect(updateScopeParentMock).toHaveBeenNthCalledWith(2, 'child-2', 'new-root-123');
        expect(updateScopeParentMock).toHaveBeenNthCalledWith(3, 'child-3', 'new-root-123');
        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Failed to move 2/3 child scopes to new root',
        });
      });

      it('returns migration_failed when all child scope moves fail', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Folder1', parentId: 'old-root-123' },
          { id: 'child-2', name: 'Folder2', parentId: 'old-root-123' },
        ]);
        updateScopeParentMock.mockRejectedValue(new Error('API error'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Failed to move 2/2 child scopes to new root',
        });
      });

      it('returns migration_failed when old root deletion has failed folders', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeRecursivelyMock.mockResolvedValue({
          successFolders: [],
          failedFolders: [
            {
              id: 'old-root-123',
              name: 'OldSiteRoot',
              path: '/OldSiteRoot',
              failReason: 'Cannot delete non-empty folder',
            },
          ],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Failed to delete old root scope',
        });
      });

      it('returns migration_failed when getScopeByExternalId throws', async () => {
        getScopeByExternalIdMock.mockRejectedValue(new Error('Network error'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Network error',
        });
        // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
        expect(service['logger'].error).toHaveBeenCalledWith(
          expect.objectContaining({ msg: expect.stringContaining('Migration failed') }),
        );
      });

      it('returns migration_failed when listChildrenScopes throws', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockRejectedValue(new Error('Failed to list children'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Failed to list children',
        });
      });

      it('returns migration_failed when deleteScopeRecursively throws', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeRecursivelyMock.mockRejectedValue(new Error('Delete operation failed'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'Delete operation failed',
        });
      });

      it('converts non-Error objects to string in error result', async () => {
        getScopeByExternalIdMock.mockRejectedValue('string error');

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'string error',
        });
      });
    });
  });
});
