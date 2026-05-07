import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import { UniqueUsersService } from '../../unique-api/unique-users/unique-users.service';
import { Smeared } from '../../utils/smeared';
import { createMockSiteConfig } from '../../utils/test-utils/mock-site-config';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { ResolveScopePathCommand } from './resolve-scope-path.command';

describe('CreateRootScopeCommand', () => {
  let service: CreateRootScopeCommand;
  let getScopeByIdMock: ReturnType<typeof vi.fn>;
  let createScopesBasedOnPathsMock: ReturnType<typeof vi.fn>;
  let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;
  let deleteScopeMock: ReturnType<typeof vi.fn>;
  let createScopeAccessesMock: ReturnType<typeof vi.fn>;
  let resolveScopePathMock: ReturnType<typeof vi.fn>;
  let getCurrentUserIdMock: ReturnType<typeof vi.fn>;

  const siteId = new Smeared('site-123', false);
  const siteName = new Smeared('My Site', false);
  const autoConfig = createMockSiteConfig({
    siteId,
    scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
  });
  const fixedConfig = createMockSiteConfig({
    siteId,
    scopeId: { type: 'fixed', scopeId: 'scope_fixed' },
  });

  beforeEach(async () => {
    getScopeByIdMock = vi.fn().mockResolvedValue({
      id: 'scope_parent',
      name: 'Parent',
      parentId: null,
      externalId: null,
    });
    createScopesBasedOnPathsMock = vi
      .fn()
      .mockResolvedValue([
        { id: 'scope_new', name: 'My Site', parentId: 'scope_parent', externalId: null },
      ]);
    updateScopeExternalIdMock = vi
      .fn()
      .mockResolvedValue({ id: 'scope_new', externalId: 'spc:site-123/site' });
    deleteScopeMock = vi.fn().mockResolvedValue({ successFolders: [], failedFolders: [] });
    createScopeAccessesMock = vi.fn();
    resolveScopePathMock = vi.fn().mockResolvedValue(new Smeared('/Parent', false));
    getCurrentUserIdMock = vi.fn().mockResolvedValue('user-123');

    const { unit } = await TestBed.solitary(CreateRootScopeCommand)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeById: getScopeByIdMock,
        createScopesBasedOnPaths: createScopesBasedOnPathsMock,
        updateScopeExternalId: updateScopeExternalIdMock,
        deleteScope: deleteScopeMock,
        createScopeAccesses: createScopeAccessesMock,
      }))
      .mock<UniqueUsersService>(UniqueUsersService)
      .impl((stubFn) => ({
        ...stubFn(),
        getCurrentUserId: getCurrentUserIdMock,
      }))
      .mock<ResolveScopePathCommand>(ResolveScopePathCommand)
      .impl((stubFn) => ({
        ...stubFn(),
        execute: resolveScopePathMock,
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

  it('throws a typed RootScopeResolutionError(invalid_scope_kind) when called with a fixed configuration', async () => {
    await expect(service.execute(fixedConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'invalid_scope_kind',
      siteId: 'site-123',
    });

    expect(createScopesBasedOnPathsMock).not.toHaveBeenCalled();
    expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    expect(getCurrentUserIdMock).not.toHaveBeenCalled();
  });

  it('rolls back every returned scope and throws claim_failed when createScopesBasedOnPaths returns more than one scope', async () => {
    createScopesBasedOnPathsMock.mockResolvedValue([
      { id: 'scope_intermediate', name: 'Parent', parentId: null, externalId: null },
      { id: 'scope_new', name: 'My Site', parentId: 'scope_intermediate', externalId: null },
    ]);

    await expect(service.execute(autoConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'claim_failed',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });

    expect(deleteScopeMock).toHaveBeenCalledWith('scope_intermediate', { recursive: true });
    expect(deleteScopeMock).toHaveBeenCalledWith('scope_new', { recursive: true });
    expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
  });

  it('grants READ on the configured parent before reading it', async () => {
    await service.execute(autoConfig, siteName);

    expect(createScopeAccessesMock).toHaveBeenCalledWith('scope_parent', [
      { type: 'READ', entityId: 'user-123', entityType: 'USER' },
    ]);
    const accessOrder = createScopeAccessesMock.mock.invocationCallOrder[0];
    const getOrder = getScopeByIdMock.mock.invocationCallOrder[0];
    expect(accessOrder).toBeDefined();
    expect(getOrder).toBeDefined();
    expect(accessOrder).toBeLessThan(getOrder as number);
  });

  it('creates the new scope under the resolved parent path and claims it', async () => {
    const result = await service.execute(autoConfig, siteName);

    expect(createScopesBasedOnPathsMock).toHaveBeenCalledWith(['/Parent/My Site'], {
      includePermissions: true,
      inheritAccess: false,
    });
    expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
      'scope_new',
      expect.objectContaining({ value: 'spc:site-123/site' }),
    );
    expect(result.rootScopeId).toBe('scope_new');
    expect(result.rootPath.value).toBe('/Parent/My Site');
    expect(deleteScopeMock).not.toHaveBeenCalled();
  });

  it('throws invalid_parent when the configured parent scope cannot be found', async () => {
    getScopeByIdMock.mockResolvedValue(null);

    await expect(service.execute(autoConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'invalid_parent',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });

    expect(createScopesBasedOnPathsMock).not.toHaveBeenCalled();
    expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
  });

  it('throws invalid_site_name when siteName is empty', async () => {
    const emptySiteName = new Smeared('', false);

    await expect(service.execute(autoConfig, emptySiteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'invalid_site_name',
      siteId: 'site-123',
      parentScopeId: 'scope_parent',
    });

    expect(getScopeByIdMock).not.toHaveBeenCalled();
    expect(createScopesBasedOnPathsMock).not.toHaveBeenCalled();
  });

  it('accepts multi-segment site names that contain slashes', async () => {
    const multiSegment = new Smeared('Parent/Sub', false);

    const result = await service.execute(autoConfig, multiSegment);

    expect(createScopesBasedOnPathsMock).toHaveBeenCalledWith(['/Parent/Parent/Sub'], {
      includePermissions: true,
      inheritAccess: false,
    });
    expect(result.rootPath.value).toBe('/Parent/Parent/Sub');
  });

  it('rolls back and throws claim_failed when createScopesBasedOnPaths returns wrong parent', async () => {
    createScopesBasedOnPathsMock.mockResolvedValue([
      {
        id: 'scope_wrong',
        name: 'My Site',
        parentId: 'unexpected_parent',
        externalId: null,
      },
    ]);

    await expect(service.execute(autoConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'claim_failed',
    });

    expect(deleteScopeMock).toHaveBeenCalledWith('scope_wrong', { recursive: true });
    expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
  });

  it('rolls back the created scope and throws claim_failed when claim step fails', async () => {
    const claimFailure = new Error('claim API down');
    updateScopeExternalIdMock.mockRejectedValueOnce(claimFailure);

    await expect(service.execute(autoConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'claim_failed',
      cause: claimFailure,
    });

    expect(deleteScopeMock).toHaveBeenCalledWith('scope_new', { recursive: true });
  });

  it('preserves the original claim error as cause when rollback also fails', async () => {
    const claimFailure = new Error('claim API down');
    const rollbackFailure = new Error('rollback API also down');
    updateScopeExternalIdMock.mockRejectedValueOnce(claimFailure);
    deleteScopeMock.mockRejectedValueOnce(rollbackFailure);

    await expect(service.execute(autoConfig, siteName)).rejects.toMatchObject({
      name: 'RootScopeResolutionError',
      code: 'claim_failed',
      cause: claimFailure,
    });

    expect(deleteScopeMock).toHaveBeenCalledWith('scope_new', { recursive: true });

    // biome-ignore lint/suspicious/noExplicitAny: Accessing private logger for testing
    const errorLogs = ((service as any).logger.error as ReturnType<typeof vi.fn>).mock.calls;
    const rollbackLogged = errorLogs.some(([arg]: unknown[]) => {
      if (arg && typeof arg === 'object' && 'msg' in arg) {
        return /roll back/i.test(String((arg as { msg: unknown }).msg));
      }
      return false;
    });
    expect(rollbackLogged).toBe(true);
  });
});
