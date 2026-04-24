import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { Smeared } from '../utils/smeared';
import { RootScopeMigrationService } from './root-scope-migration.service';

describe('RootScopeMigrationService', () => {
  let service: RootScopeMigrationService;
  let getScopeByExternalIdMock: ReturnType<typeof vi.fn>;
  let listChildrenScopesMock: ReturnType<typeof vi.fn>;
  let bulkMoveScopesMock: ReturnType<typeof vi.fn>;
  let deleteScopeMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    getScopeByExternalIdMock = vi.fn();
    listChildrenScopesMock = vi.fn();
    bulkMoveScopesMock = vi.fn();
    deleteScopeMock = vi.fn();

    const { unit } = await TestBed.solitary(RootScopeMigrationService)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeByExternalId: getScopeByExternalIdMock,
        listChildrenScopes: listChildrenScopesMock,
        bulkMoveScopes: bulkMoveScopesMock,
        deleteScope: deleteScopeMock,
      }))
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
        expect(getScopeByExternalIdMock).toHaveBeenCalledWith('spc:site-456/site');
        expect(listChildrenScopesMock).not.toHaveBeenCalled();
      });

      it('falls back to new-format lookup when legacy lookup misses', async () => {
        // After ScopeExternalIdMigrationService has run, the old root no longer carries the
        // legacy `spc:site:{id}` externalId. RootScopeMigrationService must still find it via
        // the new-format `spc:{id}/site` lookup so the root-reconfiguration path keeps working.
        getScopeByExternalIdMock.mockResolvedValueOnce(null).mockResolvedValueOnce({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site-456/site',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([
          { id: 'child-1', name: 'Folder1', parentId: 'old-root-123' },
        ]);
        bulkMoveScopesMock.mockResolvedValue({
          scopeIds: ['child-1'],
          asyncMetadataRebuild: false,
        });
        deleteScopeMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(getScopeByExternalIdMock).toHaveBeenNthCalledWith(1, 'spc:site:site-456');
        expect(getScopeByExternalIdMock).toHaveBeenNthCalledWith(2, 'spc:site-456/site');
        expect(bulkMoveScopesMock).toHaveBeenCalledWith(['child-1'], 'new-root-123');
        expect(deleteScopeMock).toHaveBeenCalledWith('old-root-123');
      });

      it('skips fallback lookup when legacy lookup hits', async () => {
        // Backwards-compatibility: tenants whose externalId migration has not yet run (or has
        // partially failed) still keep the legacy root externalId and must be picked up on the
        // first call without an extra round-trip.
        getScopeByExternalIdMock.mockResolvedValueOnce({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        await service.migrateIfNeeded('new-root-123', new Smeared('site-456', false));

        expect(getScopeByExternalIdMock).toHaveBeenCalledTimes(1);
        expect(getScopeByExternalIdMock).toHaveBeenCalledWith('spc:site:site-456');
      });

      it('returns no_migration_needed when new-format lookup finds the configured root itself', async () => {
        // Steady-state safety net: if the legacy lookup misses and the new-format lookup returns
        // the currently-configured root (because it was claimed in a previous sync), the
        // existing same-root guard must still prevent self-migration.
        getScopeByExternalIdMock.mockResolvedValueOnce(null).mockResolvedValueOnce({
          id: 'same-root-123',
          name: 'SiteRoot',
          externalId: 'spc:site-456/site',
          parentId: null,
        });

        const result = await service.migrateIfNeeded(
          'same-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'no_migration_needed' });
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
    });

    describe('migration execution', () => {
      it('bulk-moves all child scopes to new root in a single call and deletes old root', async () => {
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
        bulkMoveScopesMock.mockResolvedValue({
          scopeIds: ['child-1', 'child-2', 'child-3'],
          asyncMetadataRebuild: false,
        });
        deleteScopeMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(bulkMoveScopesMock).toHaveBeenCalledTimes(1);
        expect(bulkMoveScopesMock).toHaveBeenCalledWith(
          ['child-1', 'child-2', 'child-3'],
          'new-root-123',
        );
        expect(deleteScopeMock).toHaveBeenCalledWith('old-root-123');
      });

      it('skips bulkMoveScopes when old root has no children and still deletes old root', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeMock.mockResolvedValue({
          successFolders: [{ id: 'old-root-123', name: 'OldSiteRoot', path: '/OldSiteRoot' }],
          failedFolders: [],
        });

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({ status: 'migration_completed' });
        expect(bulkMoveScopesMock).not.toHaveBeenCalled();
        expect(deleteScopeMock).toHaveBeenCalledWith('old-root-123');
      });
    });

    describe('error handling', () => {
      it('returns migration_failed and skips old-root deletion when bulkMoveScopes throws', async () => {
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
        bulkMoveScopesMock.mockRejectedValue(new Error('bulkMove API error'));

        const result = await service.migrateIfNeeded(
          'new-root-123',
          new Smeared('site-456', false),
        );

        expect(result).toEqual({
          status: 'migration_failed',
          error: 'bulkMove API error',
        });
        expect(deleteScopeMock).not.toHaveBeenCalled();
      });

      it('returns migration_failed when old root deletion has failed folders', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeMock.mockResolvedValue({
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

      it('returns migration_failed when deleteScope throws', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-root-123',
          name: 'OldSiteRoot',
          externalId: 'spc:site:site-456',
          parentId: null,
        });
        listChildrenScopesMock.mockResolvedValue([]);
        deleteScopeMock.mockRejectedValue(new Error('Delete operation failed'));

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
