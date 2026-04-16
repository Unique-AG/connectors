import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { EXTERNAL_ID_PREFIX } from '../utils/scope-external-id';
import { Smeared } from '../utils/smeared';
import { ScopeExternalIdMigrationService } from './scope-external-id-migration.service';

const ROOT_SITE_ID = 'site-abc';

function scope(id: string, parentId: string | null, externalId: string | null): Scope {
  return { id, name: `scope-${id}`, parentId, externalId };
}

const rootScope = scope('root-1', null, `spc:site:${ROOT_SITE_ID}`);
const driveScope = scope('drive-1', 'root-1', `spc:drive:${ROOT_SITE_ID}/d1`);
const folderScope = scope('folder-1', 'drive-1', `spc:folder:${ROOT_SITE_ID}/item1`);

describe('ScopeExternalIdMigrationService', () => {
  let service: ScopeExternalIdMigrationService;
  let listScopesByExternalIdPrefixMock: ReturnType<typeof vi.fn>;
  let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    listScopesByExternalIdPrefixMock = vi.fn();
    updateScopeExternalIdMock = vi.fn();

    const { unit } = await TestBed.solitary(ScopeExternalIdMigrationService)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        listScopesByExternalIdPrefix: listScopesByExternalIdPrefixMock,
        updateScopeExternalId: updateScopeExternalIdMock,
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

  describe('migrateSiteScopes', () => {
    it('fetches scopes with the spc: prefix', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([]);

      await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(1);
      const arg = listScopesByExternalIdPrefixMock.mock.calls[0]?.[0];
      expect(arg).toBeInstanceOf(Smeared);
      expect(arg.value).toBe(EXTERNAL_ID_PREFIX);
    });

    it('returns no_migration_needed when scope list is empty', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([]);

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({ status: 'no_migration_needed' });
    });

    it('returns no_migration_needed when no root scope with legacy format exists', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([
        scope('s1', null, `spc:${ROOT_SITE_ID}/site`),
      ]);

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({ status: 'no_migration_needed' });
    });

    it('returns migration_completed when all scopes are migrated', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, folderScope]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'any', externalId: 'any' });

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({ status: 'migration_completed', migratedCount: 3 });
    });

    it('skips scopes already in new format', async () => {
      const newFormatScope = scope('new-1', 'root-1', `spc:${ROOT_SITE_ID}/drive:site/d2`);
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, newFormatScope]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'any', externalId: 'any' });

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({ status: 'migration_completed', migratedCount: 2 });
      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(2);
    });

    it('skips scopes with null externalId', async () => {
      const nullScope = scope('null-1', 'root-1', null);
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, nullScope]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'any', externalId: 'any' });

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({ status: 'migration_completed', migratedCount: 1 });
      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
    });

    it('returns migration_failed with counts on partial failure', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, folderScope]);
      updateScopeExternalIdMock
        .mockRejectedValueOnce(new Error('API error'))
        .mockResolvedValueOnce({ id: 'folder-1', externalId: 'new' })
        .mockResolvedValueOnce({ id: 'root-1', externalId: 'new' });

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        migratedCount: 2,
        failedCount: 1,
      });
    });

    it('returns migration_failed when root scope update fails', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope]);
      updateScopeExternalIdMock
        .mockResolvedValueOnce({ id: 'drive-1', externalId: 'new' })
        .mockRejectedValueOnce(new Error('Root update error'));

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        migratedCount: 1,
        failedCount: 1,
      });
    });

    it('migrates root scope last', async () => {
      const updateOrder: string[] = [];
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, folderScope]);
      updateScopeExternalIdMock.mockImplementation((scopeId: string) => {
        updateOrder.push(scopeId);
        return Promise.resolve({ id: scopeId, externalId: 'new' });
      });

      await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(updateOrder).toHaveLength(3);
      expect(updateOrder[updateOrder.length - 1]).toBe(rootScope.id);

      const rootIndex = updateOrder.indexOf(rootScope.id);
      const driveIndex = updateOrder.indexOf(driveScope.id);
      const folderIndex = updateOrder.indexOf(folderScope.id);
      expect(driveIndex).toBeLessThan(rootIndex);
      expect(folderIndex).toBeLessThan(rootIndex);
    });

    it('passes Smeared values to updateScopeExternalId', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'root-1', externalId: 'new' });

      await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
      const [scopeId, smearedArg] = updateScopeExternalIdMock.mock.calls[0] ?? [];
      expect(scopeId).toBe(rootScope.id);
      expect(smearedArg).toBeInstanceOf(Smeared);
      expect(smearedArg.value).toBe(`spc:${ROOT_SITE_ID}/site`);
    });

    it('continues migrating remaining children when one fails', async () => {
      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, folderScope]);
      updateScopeExternalIdMock
        .mockRejectedValueOnce(new Error('API error'))
        .mockResolvedValueOnce({ id: 'folder-1', externalId: 'new' })
        .mockResolvedValueOnce({ id: 'root-1', externalId: 'new' });

      await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(3);
    });

    it('returns migration_failed with zero counts when fetch fails', async () => {
      listScopesByExternalIdPrefixMock.mockRejectedValue(new Error('Network error'));

      const result = await service.migrateSiteScopes(ROOT_SITE_ID);

      expect(result).toEqual({
        status: 'migration_failed',
        migratedCount: 0,
        failedCount: 0,
      });
    });

    it('reuses cached scopes for other sites without re-fetching', async () => {
      const siteB = 'site-xyz';
      const rootB = scope('root-b', null, `spc:site:${siteB}`);

      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, rootB]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'any', externalId: 'any' });

      await service.migrateSiteScopes(ROOT_SITE_ID);
      await service.migrateSiteScopes(siteB);

      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(1);
    });

    it('evicts only the migrated site from cache after successful migration', async () => {
      const siteB = 'site-xyz';
      const rootB = scope('root-b', null, `spc:site:${siteB}`);

      listScopesByExternalIdPrefixMock.mockResolvedValue([rootScope, driveScope, rootB]);
      updateScopeExternalIdMock.mockResolvedValue({ id: 'any', externalId: 'any' });

      await service.migrateSiteScopes(ROOT_SITE_ID);
      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(1);

      // Site B's cache entry still valid — no re-fetch needed
      await service.migrateSiteScopes(siteB);
      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(1);

      // Requesting ROOT_SITE_ID again triggers re-fetch (evicted after migration)
      listScopesByExternalIdPrefixMock.mockResolvedValue([]);
      await service.migrateSiteScopes(ROOT_SITE_ID);
      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(2);
    });

    it('re-fetches when cache entry has expired', async () => {
      vi.useFakeTimers();
      try {
        listScopesByExternalIdPrefixMock.mockResolvedValue([]);

        await service.migrateSiteScopes(ROOT_SITE_ID);
        expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(1);

        vi.advanceTimersByTime(2 * 60 * 60 * 1000 + 1);

        await service.migrateSiteScopes(ROOT_SITE_ID);
        expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
