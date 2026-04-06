import type { UniqueApiClient } from '@unique-ag/unique-api';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestionConfig } from '../../config/ingestion.schema';
import type { ConfluenceApiClient } from '../../confluence-api/confluence-api-client';
import { ScopeManagementService } from '../scope-management.service';

const TENANT_NAME = 'dogfood-cloud';
const ROOT_SCOPE_ID = 'root-scope-id';
const INSTANCE_ID = 'abc-123-instance';

function makeService() {
  const scopes = {
    getById: vi.fn(),
    createFromPaths: vi.fn(),
    updateExternalId: vi.fn(),
    createAccesses: vi.fn().mockResolvedValue(undefined),
  };

  const users = {
    getCurrentId: vi.fn().mockResolvedValue('service-user-id'),
  };

  const uniqueApiClient = { scopes, users } as unknown as UniqueApiClient;

  const confluenceApi = {
    resolveInstanceIdentifier: vi.fn().mockResolvedValue({ type: 'cloud', id: INSTANCE_ID }),
  };

  const ingestionConfig = {
    scopeId: ROOT_SCOPE_ID,
  } as unknown as IngestionConfig;

  return {
    service: new ScopeManagementService(
      ingestionConfig,
      TENANT_NAME,
      confluenceApi as unknown as ConfluenceApiClient,
      uniqueApiClient,
    ),
    scopes,
    confluenceApi,
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
    const { rootScopePath } = await service.initialize();
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

      const { rootScopePath } = await service.initialize();

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

      const { rootScopePath } = await service.initialize();

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
    it('claims ownership and returns isInitialSync=true when externalId is null', async () => {
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

      const result = await service.initialize();

      expect(result.isInitialSync).toBe(true);
      expect(result.rootScopePath).toBe('/Confluence');
      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        ROOT_SCOPE_ID,
        `confc:cloud:${INSTANCE_ID}`,
      );
    });

    it('proceeds with isInitialSync=false when externalId matches', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: `confc:cloud:${INSTANCE_ID}`,
      });

      const result = await service.initialize();

      expect(result.isInitialSync).toBe(false);
      expect(result.rootScopePath).toBe('/Confluence');
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

    it('logs warning but does not throw when claim fails', async () => {
      const { service, scopes } = makeService();
      scopes.getById.mockResolvedValueOnce({
        id: ROOT_SCOPE_ID,
        name: 'Confluence',
        parentId: null,
        externalId: null,
      });
      scopes.updateExternalId.mockRejectedValueOnce(new Error('API error'));

      const result = await service.initialize();

      expect(result.isInitialSync).toBe(true);
      expect(result.rootScopePath).toBe('/Confluence');
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

      const result = await service.initialize();

      expect(result.isInitialSync).toBe(true);
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

      const result = await service.ensureSpaceScopes(rootScopePath, ['ENG', 'MKT']);

      expect(result).toEqual(
        new Map([
          ['ENG', 'scope-eng'],
          ['MKT', 'scope-mkt'],
        ]),
      );
      expect(scopes.createFromPaths).toHaveBeenCalledWith(['/Confluence/ENG', '/Confluence/MKT'], {
        inheritAccess: true,
      });
      expect(scopes.updateExternalId).toHaveBeenCalledWith('scope-eng', `confc:${TENANT_NAME}:ENG`);
      expect(scopes.updateExternalId).toHaveBeenCalledWith('scope-mkt', `confc:${TENANT_NAME}:MKT`);
    });
  });
});
