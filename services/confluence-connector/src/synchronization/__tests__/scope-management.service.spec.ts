import type pino from 'pino';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { IngestionConfig } from '../../config/ingestion.schema';
import type { UniqueApiClient } from '../../unique-api/types/unique-api-client.types';
import { ScopeManagementService } from '../scope-management.service';

const TENANT_NAME = 'dogfood-cloud';
const ROOT_SCOPE_ID = 'root-scope-id';

function makeService(): {
  service: ScopeManagementService;
  scopes: {
    getById: ReturnType<typeof vi.fn>;
    getByExternalId: ReturnType<typeof vi.fn>;
    createFromPaths: ReturnType<typeof vi.fn>;
    updateExternalId: ReturnType<typeof vi.fn>;
  };
} {
  const scopes = {
    getById: vi.fn(),
    getByExternalId: vi.fn(),
    createFromPaths: vi.fn(),
    updateExternalId: vi.fn(),
  };

  const uniqueApiClient = { scopes } as unknown as UniqueApiClient;
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
  async function initializeService(service: ScopeManagementService, scopes: ReturnType<typeof makeService>['scopes']) {
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

      await expect(service.initialize()).rejects.toThrow(`Root scope not found: ${ROOT_SCOPE_ID}`);
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

      await expect(service.initialize()).rejects.toThrow(
        'Parent scope not found: missing-parent',
      );
    });
  });

  describe('ensureSpaceScope', () => {
    it('returns cached scope on second call', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      scopes.getByExternalId.mockResolvedValueOnce({ id: 'scope-UNQ', name: 'UNQ' });

      const first = await service.ensureSpaceScope('UNQ');
      const second = await service.ensureSpaceScope('UNQ');

      expect(first).toBe('scope-UNQ');
      expect(second).toBe('scope-UNQ');
      expect(scopes.getByExternalId).toHaveBeenCalledTimes(1);
    });

    it('finds existing scope by externalId', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      scopes.getByExternalId.mockResolvedValueOnce({ id: 'existing-scope', name: 'SP' });

      const result = await service.ensureSpaceScope('SP');

      expect(result).toBe('existing-scope');
      expect(scopes.getByExternalId).toHaveBeenCalledWith(`confc:${TENANT_NAME}:SP`);
      expect(scopes.createFromPaths).not.toHaveBeenCalled();
    });

    it('creates scope when not found by externalId', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      scopes.getByExternalId.mockResolvedValueOnce(null);
      scopes.createFromPaths.mockResolvedValueOnce([{ id: 'new-scope', name: 'DEV' }]);
      scopes.updateExternalId.mockResolvedValueOnce({
        id: 'new-scope',
        externalId: `confc:${TENANT_NAME}:DEV`,
      });

      const result = await service.ensureSpaceScope('DEV');

      expect(result).toBe('new-scope');
      expect(scopes.createFromPaths).toHaveBeenCalledWith(['/Confluence/DEV'], {
        inheritAccess: true,
      });
      expect(scopes.updateExternalId).toHaveBeenCalledWith(
        'new-scope',
        `confc:${TENANT_NAME}:DEV`,
      );
    });

    it('throws when not initialized', async () => {
      const { service, scopes } = makeService();
      scopes.getByExternalId.mockResolvedValueOnce(null);

      await expect(service.ensureSpaceScope('SP')).rejects.toThrow(
        'ScopeManagementService not initialized',
      );
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

      expect(result).toEqual(new Map([
        ['ENG', 'scope-eng'],
        ['MKT', 'scope-mkt'],
      ]));
      expect(scopes.createFromPaths).toHaveBeenCalledWith(
        ['/Confluence/ENG', '/Confluence/MKT'],
        { inheritAccess: true },
      );
      expect(scopes.updateExternalId).toHaveBeenCalledWith('scope-eng', `confc:${TENANT_NAME}:ENG`);
      expect(scopes.updateExternalId).toHaveBeenCalledWith('scope-mkt', `confc:${TENANT_NAME}:MKT`);
    });

    it('deduplicates space keys before creating scopes', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      scopes.createFromPaths.mockResolvedValueOnce([{ id: 'scope-sp', name: 'SP' }]);
      scopes.updateExternalId.mockResolvedValue(undefined);

      const result = await service.ensureSpaceScopes(['SP', 'SP', 'SP']);

      expect(result).toEqual(new Map([['SP', 'scope-sp']]));
      expect(scopes.createFromPaths).toHaveBeenCalledWith(
        ['/Confluence/SP'],
        { inheritAccess: true },
      );
      expect(scopes.updateExternalId).toHaveBeenCalledTimes(1);
    });

    it('skips createFromPaths for already-cached keys and only resolves uncached ones', async () => {
      const { service, scopes } = makeService();
      await initializeService(service, scopes);

      // Populate cache for 'SP' via singular ensureSpaceScope
      scopes.getByExternalId.mockResolvedValueOnce({ id: 'scope-sp', name: 'SP' });
      await service.ensureSpaceScope('SP');

      // Now call plural with one cached ('SP') and one new ('DEV')
      scopes.createFromPaths.mockResolvedValueOnce([{ id: 'scope-dev', name: 'DEV', externalId: null }]);
      scopes.updateExternalId.mockResolvedValue(undefined);

      const result = await service.ensureSpaceScopes(['SP', 'DEV']);

      expect(scopes.createFromPaths).toHaveBeenCalledWith(
        ['/Confluence/DEV'],
        { inheritAccess: true },
      );
      expect(result).toEqual(new Map([
        ['SP', 'scope-sp'],
        ['DEV', 'scope-dev'],
      ]));
    });

    it('throws when not initialized', async () => {
      const { service } = makeService();

      await expect(service.ensureSpaceScopes(['SP'])).rejects.toThrow(
        'ScopeManagementService not initialized',
      );
    });
  });
});
