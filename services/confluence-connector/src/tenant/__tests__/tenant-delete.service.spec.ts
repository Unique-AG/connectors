import { describe, expect, it, vi } from 'vitest';
import { TenantDeleteService } from '../tenant-delete.service';

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
      getContentIdsByScope: vi.fn(),
      deleteByIds: vi.fn(),
    },
  };
}

describe('TenantDeleteService', () => {
  it('skips cleanup when root scope is not found', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue(null);

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        msg: expect.stringContaining('not found, skipping'),
      }),
    );
    expect(client.scopes.listChildren).not.toHaveBeenCalled();
  });

  it('skips cleanup when no child scopes exist', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([]);

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Already cleaned up, skipping' }),
    );
    expect(client.files.getContentIdsByScope).not.toHaveBeenCalled();
  });

  it('deletes content by scope ownership and then deletes child scopes', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope
      .mockResolvedValueOnce(['file-1', 'file-2'])
      .mockResolvedValueOnce(['file-3']);
    client.files.deleteByIds.mockResolvedValue(2);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'id', name: 'name', path: '/path' }],
      failedFolders: [],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

    expect(client.files.getContentIdsByScope).toHaveBeenCalledWith('child-1');
    expect(client.files.getContentIdsByScope).toHaveBeenCalledWith('child-2');
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-3']);
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    expect(client.scopes.delete).toHaveBeenCalledWith('child-2', { recursive: true });
    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ tenantName: 'my-tenant', msg: 'Tenant cleanup completed' }),
    );
  });

  it('skips file deletion for scopes with no content', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

    expect(client.files.deleteByIds).not.toHaveBeenCalled();
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
  });

  it('handles multiple child scopes with varying content', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
      { id: 'child-3', name: 'space-c', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope
      .mockResolvedValueOnce(['file-1', 'file-2'])
      .mockResolvedValueOnce(['file-3'])
      .mockResolvedValueOnce([]);
    client.files.deleteByIds.mockResolvedValue(2);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'id', name: 'name', path: '/path' }],
      failedFolders: [],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

    expect(client.files.getContentIdsByScope).toHaveBeenCalledTimes(3);
    expect(client.files.deleteByIds).toHaveBeenCalledTimes(2);
    expect(client.scopes.delete).toHaveBeenCalledTimes(3);
  });

  it('logs warning when scope deletion has failures', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [{ id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null }];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope.mockResolvedValue(['file-1']);
    client.files.deleteByIds.mockResolvedValue(1);
    client.scopes.delete.mockResolvedValue({
      successFolders: [],
      failedFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never);
    await service.deleteTenantContent();

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
});
