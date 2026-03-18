import { describe, expect, it, vi } from 'vitest';
import { TenantCleanupService } from '../tenant-cleanup.service';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

function createMockUniqueApiClient() {
  return {
    scopes: {
      getById: vi.fn(),
      listChildren: vi.fn(),
      delete: vi.fn(),
    },
    files: {
      getCountByKeyPrefix: vi.fn(),
      getFileIdsByScope: vi.fn(),
      deleteByIds: vi.fn(),
      deleteByKeyPrefix: vi.fn(),
    },
  };
}

function createIngestionConfig(useV1KeyFormat = false) {
  return {
    scopeId: 'scope-1',
    storeInternally: true,
    useV1KeyFormat,
    ingestionMode: 'flat',
  };
}

describe('TenantCleanupService', () => {
  it('skips cleanup when root scope is not found', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue(null);

    const service = new TenantCleanupService('my-tenant', createIngestionConfig(), client as never);
    await service.cleanup();

    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        msg: expect.stringContaining('not found, skipping'),
      }),
    );
    expect(client.scopes.listChildren).not.toHaveBeenCalled();
  });

  it('skips cleanup when already cleaned up for V2 (no children, no files)', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([]);
    client.files.getCountByKeyPrefix.mockResolvedValue(0);

    const service = new TenantCleanupService('my-tenant', createIngestionConfig(), client as never);
    await service.cleanup();

    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Already cleaned up, skipping' }),
    );
    expect(client.files.deleteByKeyPrefix).not.toHaveBeenCalled();
  });

  it('skips cleanup when already cleaned up for V1 (no children)', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([]);

    const service = new TenantCleanupService(
      'my-tenant',
      createIngestionConfig(true),
      client as never,
    );
    await service.cleanup();

    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Already cleaned up, skipping' }),
    );
    expect(client.files.getCountByKeyPrefix).not.toHaveBeenCalled();
    expect(client.files.getFileIdsByScope).not.toHaveBeenCalled();
  });

  it('deletes files by key prefix and child scopes for V2 tenants', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getCountByKeyPrefix.mockResolvedValue(5);
    client.files.deleteByKeyPrefix.mockResolvedValue(5);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantCleanupService('my-tenant', createIngestionConfig(), client as never);
    await service.cleanup();

    expect(client.files.deleteByKeyPrefix).toHaveBeenCalledWith('my-tenant');
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    expect(client.scopes.delete).toHaveBeenCalledWith('child-2', { recursive: true });
    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Tenant cleanup completed' }),
    );
  });

  it('deletes files by scope ownership for V1 tenants', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getFileIdsByScope.mockResolvedValue(['file-1', 'file-2']);
    client.files.deleteByIds.mockResolvedValue(2);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantCleanupService(
      'my-tenant',
      createIngestionConfig(true),
      client as never,
    );
    await service.cleanup();

    expect(client.files.getFileIdsByScope).toHaveBeenCalledWith('child-1');
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
    expect(client.files.deleteByKeyPrefix).not.toHaveBeenCalled();
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Tenant cleanup completed' }),
    );
  });

  it('skips file deletion for V1 scopes with no files', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getFileIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantCleanupService(
      'my-tenant',
      createIngestionConfig(true),
      client as never,
    );
    await service.cleanup();

    expect(client.files.deleteByIds).not.toHaveBeenCalled();
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
  });

  it('deletes files by scope ownership for V1 tenants with multiple child scopes', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
      { id: 'child-3', name: 'space-c', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getFileIdsByScope
      .mockResolvedValueOnce(['file-1', 'file-2'])
      .mockResolvedValueOnce(['file-3'])
      .mockResolvedValueOnce([]);
    client.files.deleteByIds.mockResolvedValue(2);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'id', name: 'name', path: '/path' }],
      failedFolders: [],
    });

    const service = new TenantCleanupService(
      'my-tenant',
      createIngestionConfig(true),
      client as never,
    );
    await service.cleanup();

    expect(client.files.getFileIdsByScope).toHaveBeenCalledTimes(3);
    expect(client.files.getFileIdsByScope).toHaveBeenCalledWith('child-1');
    expect(client.files.getFileIdsByScope).toHaveBeenCalledWith('child-2');
    expect(client.files.getFileIdsByScope).toHaveBeenCalledWith('child-3');
    expect(client.files.deleteByIds).toHaveBeenCalledTimes(2);
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-3']);
    expect(client.scopes.delete).toHaveBeenCalledTimes(3);
  });

  it('logs warning when scope deletion has failures', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getCountByKeyPrefix.mockResolvedValue(5);
    client.files.deleteByKeyPrefix.mockResolvedValue(5);
    client.scopes.delete.mockResolvedValue({
      successFolders: [],
      failedFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
    });

    const service = new TenantCleanupService('my-tenant', createIngestionConfig(), client as never);
    await service.cleanup();

    expect(mockLogger.warn).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        scopeName: 'space-a',
        msg: 'Partial scope deletion failure',
      }),
    );
    expect(mockLogger.warn).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        msg: 'Tenant cleanup completed with scope deletion failures',
      }),
    );
  });

  it('still proceeds with scope deletion when V2 has children but zero files', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getCountByKeyPrefix.mockResolvedValue(0);
    client.files.deleteByKeyPrefix.mockResolvedValue(0);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantCleanupService('my-tenant', createIngestionConfig(), client as never);
    await service.cleanup();

    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Tenant cleanup completed' }),
    );
  });
});
