import type { UniqueApiClient } from '@unique-ag/unique-api';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestionConfig } from '../../config/ingestion.schema';
import type { ConfluenceApiClient } from '../../confluence-api/confluence-api-client';
import type { Metrics } from '../../metrics';
import type { RootScopeMigrationService } from '../root-scope-migration.service';
import { ScopeManagementService } from '../scope-management.service';

const TENANT_NAME = 'dogfood-cloud';
const ROOT_SCOPE_ID = 'root-scope-id';
const INSTANCE_ID = 'abc-123-instance';

interface MockDeps {
  service: ScopeManagementService;
  scopes: {
    getById: ReturnType<typeof vi.fn>;
    createFromPaths: ReturnType<typeof vi.fn>;
    updateExternalId: ReturnType<typeof vi.fn>;
    createAccesses: ReturnType<typeof vi.fn>;
    listChildren: ReturnType<typeof vi.fn>;
    delete: ReturnType<typeof vi.fn>;
  };
  files: {
    deleteByKeyPrefix: ReturnType<typeof vi.fn>;
  };
  confluenceApi: {
    resolveInstanceIdentifier: ReturnType<typeof vi.fn>;
  };
  metrics: {
    recordOrphanedScopesCleaned: ReturnType<typeof vi.fn>;
    recordOrphanedFilesCleaned: ReturnType<typeof vi.fn>;
  };
  migrationService: {
    migrateIfNeeded: ReturnType<typeof vi.fn>;
  };
}

function makeService(options?: { useV1KeyFormat?: boolean }): MockDeps {
  const scopes = {
    getById: vi.fn(),
    createFromPaths: vi.fn(),
    updateExternalId: vi.fn(),
    createAccesses: vi.fn().mockResolvedValue(undefined),
    listChildren: vi.fn().mockResolvedValue([]),
    delete: vi.fn().mockResolvedValue(undefined),
  };

  const files = {
    deleteByKeyPrefix: vi.fn().mockResolvedValue(0),
  };

  const users = {
    getCurrentId: vi.fn().mockResolvedValue('service-user-id'),
  };

  const uniqueApiClient = { scopes, files, users } as unknown as UniqueApiClient;

  const confluenceApi = {
    resolveInstanceIdentifier: vi.fn().mockResolvedValue({ type: 'cloud', id: INSTANCE_ID }),
  };

  const ingestionConfig = {
    scopeId: ROOT_SCOPE_ID,
    useV1KeyFormat: options?.useV1KeyFormat ?? false,
  } as unknown as IngestionConfig;

  const metrics = {
    recordOrphanedScopesCleaned: vi.fn(),
    recordOrphanedFilesCleaned: vi.fn(),
  };

  const migrationService = {
    migrateIfNeeded: vi.fn().mockResolvedValue({ status: 'no_migration_needed' }),
  };

  return {
    service: new ScopeManagementService(
      ingestionConfig,
      TENANT_NAME,
      confluenceApi as unknown as ConfluenceApiClient,
      uniqueApiClient,
      metrics as unknown as Metrics,
      migrationService as unknown as RootScopeMigrationService,
    ),
    scopes,
    files,
    confluenceApi,
    metrics,
    migrationService,
  };
}

describe('ScopeManagementService', () => {
  async function initializeService(
    service: ScopeManagementService,
    scopes: ReturnType<typeof makeService>['scopes'],
  ): Promise<string> {
    scopes.getById.mockResolvedValueOnce({
      id: ROOT_SCOPE_ID,
      name: 'Confluence',
      parentId: null,
      externalId: `confc:cloud:${INSTANCE_ID}`,
    });
    scopes.updateExternalId.mockResolvedValue({ id: ROOT_SCOPE_ID, externalId: null });
    const rootScopePath = await service.initialize();
    scopes.getById.mockReset();
    scopes.updateExternalId.mockReset();
    return rootScopePath;
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('initialize', () => {
    it('builds root scope path from scope hierarchy', async () => {
      const { service, scopes } = makeService();
      scopes.getById
        .mockResolvedValueOnce({
          id: ROOT_SCOPE_ID,
          name: 'Confluence',
          parentId: 'parent-1',
          externalId: `confc:cloud:${INSTANCE_ID}`,
        })
        .mockResolvedValueOnce({ id: 'parent-1', name: 'Connectors', parentId: 'top-1' })
        .mockResolvedValueOnce({ id: 'top-1', name: 'Company', parentId: null });

      const rootScopePath = await service.initialize();

      expect(rootScopePath).toBe('/Company/Connectors/Confluence');
      expect(scopes.getById).toHaveBeenCalledTimes(3);
      expect(scopes.getById).toHaveBeenCalledWith(ROOT_SCOPE_ID);
      expect(scopes.getById).toHaveBeenCalledWith('parent-1');
      expect(scopes.getById).toHaveBeenCalledWith('top-1');
    });

    it('handles root scope with no parent', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'RootScope',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });

      const rootScopePath = await service.initialize();

      expect(rootScopePath).toBe('/RootScope');
      expect(scopes.getById).toHaveBeenCalledTimes(1);
    });

    it('throws when root scope is not found', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce(null);

      await expect(service.initialize()).rejects.toThrow(
        `Root scope with ID ${ROOT_SCOPE_ID} not found`,
      );
    });

    it('throws when a parent scope is not found', async () => {
      const { service, scopes } = makeService();
      scopes.getById
        .mockResolvedValueOnce({
          id: ROOT_SCOPE_ID,
          name: 'Confluence',
          parentId: 'missing-parent',
          externalId: `confc:cloud:${INSTANCE_ID}`,
        })
        .mockResolvedValueOnce(null);

      await expect(service.initialize()).rejects.toThrow('Parent scope not found: missing-parent');
    });
  });

  describe('ownership validation', () => {
    it('claims ownership when externalId is null', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      scopes.updateExternalId.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });

      const rootScopePath = await service.initialize();

      expect(rootScopePath).toBe('/Confluence');
      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        ROOT_SCOPE_ID,
        `confc:cloud:${INSTANCE_ID}`,
      );
    });

    it('runs root-scope migration before claiming when externalId is null', async () => {
      const { service, scopes, migrationService } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });

      const callOrder: string[] = [];
      migrationService.migrateIfNeeded.mockImplementationOnce(async () => {
        callOrder.push('migrateIfNeeded');
        return { status: 'no_migration_needed' };
      });
      scopes.updateExternalId.mockImplementationOnce(async () => {
        callOrder.push('updateExternalId');
        return { id: ROOT_SCOPE_ID, externalId: `confc:cloud:${INSTANCE_ID}` };
      });

      await service.initialize();

      expect(migrationService.migrateIfNeeded).toHaveBeenCalledWith(
        ROOT_SCOPE_ID,
        `confc:cloud:${INSTANCE_ID}`,
      );
      expect(callOrder).toEqual(['migrateIfNeeded', 'updateExternalId']);
    });

    it('throws when root-scope migration fails and does not call updateExternalId', async () => {
      const { service, scopes, migrationService } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      migrationService.migrateIfNeeded.mockResolvedValueOnce({
        status: 'migration_failed',
        error: 'boom',
      });

      await expect(service.initialize()).rejects.toThrow('Root scope migration failed: boom');
      expect(scopes.updateExternalId).not.toHaveBeenCalled();
    });

    it('skips migration when externalId already matches', async () => {
      const { service, scopes, migrationService } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });

      await service.initialize();

      expect(migrationService.migrateIfNeeded).not.toHaveBeenCalled();
    });

    it('skips claim when externalId already matches', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });

      const rootScopePath = await service.initialize();

      expect(rootScopePath).toBe('/Confluence');
      expect(scopes.updateExternalId).not.toHaveBeenCalled();
    });

    it('throws on ownership mismatch when externalId differs', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: 'confc:cloud:other-instance',
      });

      await expect(service.initialize()).rejects.toThrow(
        `Root scope ownership mismatch: expected confc:cloud:${INSTANCE_ID}, found confc:cloud:other-instance`,
      );
    });

    it('throws when updateExternalId returns a different externalId than expected', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      scopes.updateExternalId.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        externalId: null,
      });

      await expect(service.initialize()).rejects.toThrow(
        'Root scope ownership mismatch after claim',
      );
    });

    it('throws when claim fails', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      scopes.updateExternalId.mockRejectedValueOnce(new Error('API error'));

      await expect(service.initialize()).rejects.toThrow('API error');
    });

    it('caches instance identifier across multiple calls', async () => {
      const { service, scopes, confluenceApi } = makeService();

      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });
      await service.initialize();

      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });
      await service.initialize();

      expect(confluenceApi.resolveInstanceIdentifier).toHaveBeenCalledTimes(1);
    });

    it('builds correct externalId for data-center instance type', async () => {
      const { service, scopes, confluenceApi } = makeService();
      confluenceApi.resolveInstanceIdentifier.mockResolvedValue({
        type: 'data-center',
        id: 'dc-instance-456',
      });

      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      scopes.updateExternalId.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        externalId: 'confc:data-center:dc-instance-456',
      });

      await service.initialize();

      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        ROOT_SCOPE_ID,
        'confc:data-center:dc-instance-456',
      );
    });
  });

  describe('ensureSpaceScopes', () => {
    it('batch-resolves multiple space keys via createFromPaths and sets externalIds', async () => {
      const { service, scopes } = makeService();
      const rootScopePath = await initializeService(service, scopes);

      scopes.createFromPaths.mockResolvedValueOnce([
        { id: 'scope-eng', name: 'ENG' },
        { id: 'scope-mkt', name: 'MKT' },
      ]);
      scopes.updateExternalId.mockResolvedValue(undefined);

      const spaceKeyToSpaceId = new Map([
        ['ENG', 'eng-space-id'],
        ['MKT', 'mkt-space-id'],
      ]);
      const result = await service.ensureSpaceScopes(
        rootScopePath,
        ['ENG', 'MKT'],
        spaceKeyToSpaceId,
      );

      expect(result).toEqual(
        new Map([
          ['ENG', 'scope-eng'],
          ['MKT', 'scope-mkt'],
        ]),
      );
      expect(scopes.createFromPaths).toHaveBeenCalledWith(['/Confluence/ENG', '/Confluence/MKT'], {
        inheritAccess: true,
      });
      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        'scope-eng',
        `confc:${TENANT_NAME}:eng-space-id:ENG`,
      );
      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        'scope-mkt',
        `confc:${TENANT_NAME}:mkt-space-id:MKT`,
      );
    });

    it('skips updateExternalId when scope already has the correct externalId', async () => {
      const { service, scopes } = makeService();
      const rootScopePath = await initializeService(service, scopes);

      scopes.createFromPaths.mockResolvedValueOnce([
        { id: 'scope-eng', name: 'ENG', externalId: `confc:${TENANT_NAME}:eng-space-id:ENG` },
      ]);

      const spaceKeyToSpaceId = new Map([['ENG', 'eng-space-id']]);
      await service.ensureSpaceScopes(rootScopePath, ['ENG'], spaceKeyToSpaceId);

      expect(scopes.updateExternalId).not.toHaveBeenCalled();
    });

    it('migrates old-format externalId to new format', async () => {
      const { service, scopes } = makeService();
      const rootScopePath = await initializeService(service, scopes);

      scopes.createFromPaths.mockResolvedValueOnce([
        { id: 'scope-eng', name: 'ENG', externalId: `confc:${TENANT_NAME}:ENG` },
      ]);
      scopes.updateExternalId.mockResolvedValue(undefined);

      const spaceKeyToSpaceId = new Map([['ENG', 'eng-space-id']]);
      await service.ensureSpaceScopes(rootScopePath, ['ENG'], spaceKeyToSpaceId);

      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        'scope-eng',
        `confc:${TENANT_NAME}:eng-space-id:ENG`,
      );
    });
  });

  describe('cleanupRemovedSpaces', () => {
    it('skips cleanup when discovery returned zero spaces', async () => {
      const { service, scopes } = makeService();

      await service.cleanupRemovedSpaces(new Set());

      expect(scopes.listChildren).not.toHaveBeenCalled();
    });

    const orphanedScope = {
      id: 'scope-old',
      name: 'OLD',
      externalId: `confc:${TENANT_NAME}:old-space-id:OLD`,
    };

    const activeScope = {
      id: 'scope-eng',
      name: 'ENG',
      externalId: `confc:${TENANT_NAME}:eng-space-id:ENG`,
    };

    it('deletes files and scope for orphaned spaces', async () => {
      const { service, scopes, files, metrics } = makeService();
      scopes.listChildren.mockResolvedValue([orphanedScope, activeScope]);
      files.deleteByKeyPrefix.mockResolvedValue(5);

      await service.cleanupRemovedSpaces(new Set(['ENG']));

      expect(files.deleteByKeyPrefix).toHaveBeenCalledWith(`${TENANT_NAME}/old-space-id_OLD`);
      expect(scopes.delete).toHaveBeenCalledWith('scope-old');
      expect(files.deleteByKeyPrefix).toHaveBeenCalledTimes(1);
      expect(scopes.delete).toHaveBeenCalledTimes(1);
      expect(metrics.recordOrphanedScopesCleaned).toHaveBeenCalledWith(1, 'success');
      expect(metrics.recordOrphanedFilesCleaned).toHaveBeenCalledWith(5);
    });

    it('skips spaces that are still discovered', async () => {
      const { service, scopes, files } = makeService();
      scopes.listChildren.mockResolvedValue([activeScope]);

      await service.cleanupRemovedSpaces(new Set(['ENG']));

      expect(files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('skips scopes with missing externalId and logs error', async () => {
      const { service, scopes, files } = makeService();
      const scopeWithoutExtId = { id: 'scope-no-ext', name: 'NO_EXT', externalId: null };
      scopes.listChildren.mockResolvedValue([scopeWithoutExtId]);

      await service.cleanupRemovedSpaces(new Set(['UNRELATED']));

      expect(files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('skips scopes with unparseable externalId and logs error', async () => {
      const { service, scopes, files } = makeService();
      const scopeWithOldFormat = {
        id: 'scope-old-fmt',
        name: 'OLDFMT',
        externalId: `confc:${TENANT_NAME}:OLDFMT`,
      };
      scopes.listChildren.mockResolvedValue([scopeWithOldFormat]);

      await service.cleanupRemovedSpaces(new Set(['UNRELATED']));

      expect(files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('handles per-space errors without blocking other cleanups', async () => {
      const { service, scopes, files, metrics } = makeService();
      const secondOrphan = {
        id: 'scope-second',
        name: 'SECOND',
        externalId: `confc:${TENANT_NAME}:second-space-id:SECOND`,
      };
      scopes.listChildren.mockResolvedValue([orphanedScope, secondOrphan]);
      files.deleteByKeyPrefix
        .mockRejectedValueOnce(new Error('API failure'))
        .mockResolvedValueOnce(3);

      await service.cleanupRemovedSpaces(new Set(['UNRELATED']));

      expect(files.deleteByKeyPrefix).toHaveBeenCalledTimes(2);
      expect(scopes.delete).toHaveBeenCalledWith('scope-second');
      expect(scopes.delete).toHaveBeenCalledTimes(1);
      expect(metrics.recordOrphanedScopesCleaned).toHaveBeenCalledWith(1, 'failure');
      expect(metrics.recordOrphanedScopesCleaned).toHaveBeenCalledWith(1, 'success');
      expect(metrics.recordOrphanedFilesCleaned).toHaveBeenCalledWith(3);
    });

    it('does nothing when no orphaned scopes exist', async () => {
      const { service, scopes, files } = makeService();
      scopes.listChildren.mockResolvedValue([activeScope]);

      await service.cleanupRemovedSpaces(new Set(['ENG']));

      expect(files.deleteByKeyPrefix).not.toHaveBeenCalled();
      expect(scopes.delete).not.toHaveBeenCalled();
    });

    it('uses V1 key format when configured', async () => {
      const { service, scopes, files } = makeService({ useV1KeyFormat: true });
      scopes.listChildren.mockResolvedValue([orphanedScope]);
      files.deleteByKeyPrefix.mockResolvedValue(2);

      await service.cleanupRemovedSpaces(new Set(['UNRELATED']));

      expect(files.deleteByKeyPrefix).toHaveBeenCalledWith('old-space-id_OLD');
    });

    it('uses V2 key format with tenant prefix when not V1', async () => {
      const { service, scopes, files } = makeService({ useV1KeyFormat: false });
      scopes.listChildren.mockResolvedValue([orphanedScope]);
      files.deleteByKeyPrefix.mockResolvedValue(2);

      await service.cleanupRemovedSpaces(new Set(['UNRELATED']));

      expect(files.deleteByKeyPrefix).toHaveBeenCalledWith(`${TENANT_NAME}/old-space-id_OLD`);
    });
  });
});
