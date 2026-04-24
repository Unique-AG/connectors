import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createNoopMetrics } from '../../metrics/__mocks__/noop-metrics';
import type { TenantContext } from '../tenant-context.interface';
import { tenantStorage } from '../tenant-context.storage';
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
      updateExternalId: vi.fn().mockResolvedValue({ id: 'scope-1', externalId: null }),
    },
    files: {
      getContentIdsByScope: vi.fn(),
      deleteByIds: vi.fn(),
    },
  };
}

function createTenant(): TenantContext {
  return {
    name: 'my-tenant',
    config: {} as TenantContext['config'],
    status: 'deleted',
    isScanning: false,
  };
}

function createService(client: ReturnType<typeof createMockUniqueApiClient>) {
  return new TenantDeleteService('my-tenant', 'scope-1', client as never, createNoopMetrics());
}

function runInTenantContext<T>(tenant: TenantContext, fn: () => Promise<T>): Promise<T> {
  return tenantStorage.run(tenant, fn);
}

describe('TenantDeleteService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('skips cleanup when root scope is not found', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue(null);

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'skipped', reason: 'root_scope_not_found' });
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

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'skipped', reason: 'already_cleaned_up' });
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

    await runInTenantContext(createTenant(), () => createService(client).deleteTenantContent());

    expect(client.files.getContentIdsByScope).toHaveBeenCalledWith('child-1');
    expect(client.files.getContentIdsByScope).toHaveBeenCalledWith('child-2');
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-1', 'file-2']);
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-3']);
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
    expect(client.scopes.delete).toHaveBeenCalledWith('child-2', { recursive: true });
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

    await runInTenantContext(createTenant(), () => createService(client).deleteTenantContent());

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

    await runInTenantContext(createTenant(), () => createService(client).deleteTenantContent());

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

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(mockLogger.warn).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        scopeName: 'space-a',
        msg: 'Partial scope deletion failure',
      }),
    );
  });

  it('continues deleting remaining scopes when content deletion fails for one scope', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope
      .mockRejectedValueOnce(new Error('API error'))
      .mockResolvedValueOnce(['file-1']);
    client.files.deleteByIds.mockResolvedValue(1);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'id', name: 'name', path: '/path' }],
      failedFolders: [],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(mockLogger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        scopeName: 'space-a',
        msg: 'Failed to delete content for scope',
      }),
    );
    expect(client.files.getContentIdsByScope).toHaveBeenCalledWith('child-2');
    expect(client.files.deleteByIds).toHaveBeenCalledWith(['file-1']);
    expect(client.scopes.delete).toHaveBeenCalledTimes(2);
  });

  it('continues deleting remaining scopes when scope deletion throws for one scope', async () => {
    const client = createMockUniqueApiClient();
    const childScopes = [
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
      { id: 'child-2', name: 'space-b', parentId: 'scope-1', externalId: null },
    ];

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue(childScopes);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockRejectedValueOnce(new Error('Scope API error')).mockResolvedValueOnce({
      successFolders: [{ id: 'child-2', name: 'space-b', path: '/root/space-b' }],
      failedFolders: [],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(mockLogger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        scopeName: 'space-a',
        msg: 'Failed to delete child scope',
      }),
    );
    expect(client.scopes.delete).toHaveBeenCalledWith('child-2', { recursive: true });
  });

  it('records cleanup metrics on success', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const durationSpy = vi.spyOn(metrics, 'recordCleanupDuration');
    const contentSpy = vi.spyOn(metrics, 'recordCleanupContentDeleted');
    const scopesSpy = vi.spyOn(metrics, 'recordCleanupScopesDeleted');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue(['file-1', 'file-2']);
    client.files.deleteByIds.mockResolvedValue(2);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);
    await runInTenantContext(createTenant(), () => service.deleteTenantContent());

    expect(durationSpy).toHaveBeenCalledWith(expect.any(Number), 'success');
    expect(contentSpy).toHaveBeenCalledWith(2, 'success');
    expect(scopesSpy).toHaveBeenCalledWith(1, 'success');
  });

  it('skips cleanup when already in progress', async () => {
    const client = createMockUniqueApiClient();
    const tenant = createTenant();
    tenant.isScanning = true;

    const result = await runInTenantContext(tenant, () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'skipped', reason: 'scan_in_progress' });
    expect(mockLogger.log).toHaveBeenCalledWith(
      expect.objectContaining({ msg: 'Cleanup already in progress, skipping' }),
    );
    expect(client.scopes.getById).not.toHaveBeenCalled();
  });

  it('resets isScanning after successful cleanup', async () => {
    const client = createMockUniqueApiClient();
    const tenant = createTenant();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([]);

    await runInTenantContext(tenant, () => createService(client).deleteTenantContent());

    expect(tenant.isScanning).toBe(false);
  });

  it('resets isScanning after failed cleanup', async () => {
    const client = createMockUniqueApiClient();
    const tenant = createTenant();
    client.scopes.getById.mockRejectedValue(new Error('API down'));

    await expect(
      runInTenantContext(tenant, () => createService(client).deleteTenantContent()),
    ).rejects.toThrow('API down');

    expect(tenant.isScanning).toBe(false);
  });

  it('records cleanup duration with failure when an API call throws', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const durationSpy = vi.spyOn(metrics, 'recordCleanupDuration');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockRejectedValue(new Error('API down'));

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);

    await expect(
      runInTenantContext(createTenant(), () => service.deleteTenantContent()),
    ).rejects.toThrow('API down');

    expect(durationSpy).toHaveBeenCalledWith(expect.any(Number), 'failure');
  });

  it('does not record cleanup duration for no-op early returns', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const durationSpy = vi.spyOn(metrics, 'recordCleanupDuration');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([]);

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);
    await runInTenantContext(createTenant(), () => service.deleteTenantContent());

    expect(durationSpy).not.toHaveBeenCalled();
  });

  it('records scope metrics for both succeeded and failed folders in partial failure', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const scopesSpy = vi.spyOn(metrics, 'recordCleanupScopesDeleted');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue(['file-1']);
    client.files.deleteByIds.mockResolvedValue(1);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'sub-1', name: 'sub', path: '/root/space-a/sub' }],
      failedFolders: [
        { id: 'sub-2', name: 'sub2', path: '/root/space-a/sub2' },
        { id: 'sub-3', name: 'sub3', path: '/root/space-a/sub3' },
      ],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);
    const result = await runInTenantContext(createTenant(), () => service.deleteTenantContent());

    expect(result).toEqual({ status: 'failure', failures: 2 });
    expect(scopesSpy).toHaveBeenCalledWith(1, 'success');
    expect(scopesSpy).toHaveBeenCalledWith(2, 'failure');
  });

  it('still attempts scope deletion for scopes where content deletion failed', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockRejectedValue(new Error('API error'));
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(client.scopes.delete).toHaveBeenCalledWith('child-1', { recursive: true });
  });

  it('records cleanup duration as failure when any sub-operation failed', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const durationSpy = vi.spyOn(metrics, 'recordCleanupDuration');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [],
      failedFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);
    const result = await runInTenantContext(createTenant(), () => service.deleteTenantContent());

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(durationSpy).toHaveBeenCalledTimes(1);
    expect(durationSpy).toHaveBeenCalledWith(expect.any(Number), 'failure');
  });

  it('clears root scope externalId after successful deletion', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({
      id: 'scope-1',
      name: 'root',
      externalId: 'tenant:my-tenant',
    });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'success' });
    expect(client.scopes.updateExternalId).toHaveBeenCalledWith('scope-1', null);
  });

  it('does not clear externalId when deletion had failures', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({
      id: 'scope-1',
      name: 'root',
      externalId: 'tenant:my-tenant',
    });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [],
      failedFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(client.scopes.updateExternalId).not.toHaveBeenCalled();
  });

  it('does not clear externalId when it is already null', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root', externalId: null });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'success' });
    expect(client.scopes.updateExternalId).not.toHaveBeenCalled();
  });

  it('counts failure to clear externalId toward overall failure count', async () => {
    const client = createMockUniqueApiClient();
    client.scopes.getById.mockResolvedValue({
      id: 'scope-1',
      name: 'root',
      externalId: 'tenant:my-tenant',
    });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockResolvedValue([]);
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });
    client.scopes.updateExternalId.mockRejectedValue(new Error('API error'));

    const result = await runInTenantContext(createTenant(), () =>
      createService(client).deleteTenantContent(),
    );

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(mockLogger.error).toHaveBeenCalledWith(
      expect.objectContaining({
        tenantName: 'my-tenant',
        msg: 'Failed to clear root scope externalId',
      }),
    );
  });

  it('records content deletion failure metric when content deletion throws', async () => {
    const client = createMockUniqueApiClient();
    const metrics = createNoopMetrics();
    const contentSpy = vi.spyOn(metrics, 'recordCleanupContentDeleted');

    client.scopes.getById.mockResolvedValue({ id: 'scope-1', name: 'root' });
    client.scopes.listChildren.mockResolvedValue([
      { id: 'child-1', name: 'space-a', parentId: 'scope-1', externalId: null },
    ]);
    client.files.getContentIdsByScope.mockRejectedValue(new Error('API error'));
    client.scopes.delete.mockResolvedValue({
      successFolders: [{ id: 'child-1', name: 'space-a', path: '/root/space-a' }],
      failedFolders: [],
    });

    const service = new TenantDeleteService('my-tenant', 'scope-1', client as never, metrics);
    const result = await runInTenantContext(createTenant(), () => service.deleteTenantContent());

    expect(result).toEqual({ status: 'failure', failures: 1 });
    expect(contentSpy).toHaveBeenCalledWith(0, 'failure');
  });
});
