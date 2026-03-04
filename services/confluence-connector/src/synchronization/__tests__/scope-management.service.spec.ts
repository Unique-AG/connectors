import type { UniqueApiClient } from '@unique-ag/unique-api';
import type pino from 'pino';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestionConfig } from '../../config/ingestion.schema';
import { ScopeManagementService } from '../scope-management.service';

const TENANT_NAME = 'dogfood-cloud';
const ROOT_SCOPE_ID = 'root-scope-id';

function makeService(): {
  service: ScopeManagementService;
  scopes: {
    getById: ReturnType<typeof vi.fn>;
    createFromPaths: ReturnType<typeof vi.fn>;
    updateExternalId: ReturnType<typeof vi.fn>;
    createAccesses: ReturnType<typeof vi.fn>;
  };
} {
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
  const logger = { info: vi.fn(), debug: vi.fn(), error: vi.fn() } as unknown as pino.Logger;

  const ingestionConfig = {
    scopeId: ROOT_SCOPE_ID,
  } as unknown as IngestionConfig;

  return {
    service: new ScopeManagementService(ingestionConfig, TENANT_NAME, uniqueApiClient, logger),
    scopes,
  };
}

describe('ScopeManagementService', () => {
  async function initializeService(
    service: ScopeManagementService,
    scopes: ReturnType<typeof makeService>['scopes'],
  ) {
    scopes.getById.mockResolvedValueOnce({
      id: ROOT_SCOPE_ID,
      name: 'Confluence',
      parentId: null,
    });
    await service.initialize();
    scopes.getById.mockReset();
  }

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('initialize', () => {
    it('builds root scope path from scope hierarchy', async () => {
      const { service, scopes } = makeService();
      scopes.getById
        .mockResolvedValueOnce({ id: ROOT_SCOPE_ID, name: 'Confluence', parentId: 'parent-1' })
        .mockResolvedValueOnce({ id: 'parent-1', name: 'Connectors', parentId: 'top-1' })
        .mockResolvedValueOnce({ id: 'top-1', name: 'Company', parentId: null });

      await service.initialize();

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
      });

      await service.initialize();

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
        })
        .mockResolvedValueOnce(null);

      await expect(service.initialize()).rejects.toThrow('Parent scope not found: missing-parent');
    });
  });

  describe('ensureSpaceScopes', () => {
    it('batch-resolves multiple space keys via createFromPaths and sets externalIds', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      scopes.createFromPaths.mockResolvedValueOnce([
        { id: 'scope-eng', name: 'ENG' },
        { id: 'scope-mkt', name: 'MKT' },
      ]);
      scopes.updateExternalId.mockResolvedValue(undefined);

      const result = await service.ensureSpaceScopes(['ENG', 'MKT']);

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

    it('throws when not initialized', async () => {
      const { service } = makeService();

      await expect(service.ensureSpaceScopes(['SP'])).rejects.toThrow(
        'ScopeManagementService not initialized',
      );
    });
  });
});
