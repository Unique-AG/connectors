import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ScopeExternalIdMigrationService } from '../../scope-external-id-migration/scope-external-id-migration.service';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import { UniqueUsersService } from '../../unique-api/unique-users/unique-users.service';
import { createSmeared, Smeared } from '../../utils/smeared';
import { createMockSiteConfig } from '../../utils/test-utils/mock-site-config';
import { RootScopeMigrationService } from '../root-scope-migration.service';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { FindRootScopeQuery } from './find-root-scope.query';
import { InitializeRootScopeCommand } from './initialize-root-scope.command';
import { ResolveScopePathCommand } from './resolve-scope-path.command';
import { RootScopeResolutionError } from './root-scope-resolution.error';

describe('InitializeRootScopeCommand', () => {
  let command: InitializeRootScopeCommand;
  let getScopeByIdMock: ReturnType<typeof vi.fn>;
  let createScopeAccessesMock: ReturnType<typeof vi.fn>;
  let getCurrentUserIdMock: ReturnType<typeof vi.fn>;
  let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;
  let updateScopeParentMock: ReturnType<typeof vi.fn>;
  let rootMigrationMock: ReturnType<typeof vi.fn>;
  let externalIdMigrationMock: ReturnType<typeof vi.fn>;
  let resolveScopePathMock: ReturnType<typeof vi.fn>;
  let findRootScopeMock: ReturnType<typeof vi.fn>;
  let createRootScopeMock: ReturnType<typeof vi.fn>;

  const siteName = createSmeared('test-site-name');

  beforeEach(async () => {
    getScopeByIdMock = vi.fn();
    createScopeAccessesMock = vi.fn();
    getCurrentUserIdMock = vi.fn().mockResolvedValue('user-123');
    updateScopeExternalIdMock = vi.fn().mockResolvedValue({ externalId: 'updated-external-id' });
    updateScopeParentMock = vi.fn().mockResolvedValue({ id: 'x', parentId: 'y' });
    rootMigrationMock = vi.fn().mockResolvedValue({ status: 'no_migration_needed' });
    externalIdMigrationMock = vi.fn().mockResolvedValue({ status: 'no_migration_needed' });
    resolveScopePathMock = vi.fn().mockResolvedValue(new Smeared('/Root/test1', false));
    findRootScopeMock = vi.fn().mockResolvedValue(null);
    createRootScopeMock = vi.fn().mockResolvedValue({
      rootScopeId: 'created-root',
      rootPath: createSmeared('/created/path'),
    });

    const { unit } = await TestBed.solitary(InitializeRootScopeCommand)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        getScopeById: getScopeByIdMock,
        createScopeAccesses: createScopeAccessesMock,
        updateScopeExternalId: updateScopeExternalIdMock,
        updateScopeParent: updateScopeParentMock,
      }))
      .mock<UniqueUsersService>(UniqueUsersService)
      .impl((stubFn) => ({
        ...stubFn(),
        getCurrentUserId: getCurrentUserIdMock,
      }))
      .mock<RootScopeMigrationService>(RootScopeMigrationService)
      .impl((stubFn) => ({
        ...stubFn(),
        migrateIfNeeded: rootMigrationMock,
      }))
      .mock<ScopeExternalIdMigrationService>(ScopeExternalIdMigrationService)
      .impl((stubFn) => ({
        ...stubFn(),
        migrateIfNeeded: externalIdMigrationMock,
      }))
      .mock<ResolveScopePathCommand>(ResolveScopePathCommand)
      .impl((stubFn) => ({
        ...stubFn(),
        execute: resolveScopePathMock,
      }))
      .mock<FindRootScopeQuery>(FindRootScopeQuery)
      .impl((stubFn) => ({
        ...stubFn(),
        execute: findRootScopeMock,
      }))
      .mock<CreateRootScopeCommand>(CreateRootScopeCommand)
      .impl((stubFn) => ({
        ...stubFn(),
        execute: createRootScopeMock,
      }))
      .compile();

    command = unit;

    Object.defineProperty(command, 'logger', {
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

  describe('initialize logic (post-resolution)', () => {
    const fixedConfig = createMockSiteConfig({
      siteId: new Smeared('site-123', false),
      scopeId: { type: 'fixed', scopeId: 'root-scope-123' },
    });

    it('claims the root scope if externalId is missing', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: null,
        parentId: null,
      });

      const externalId = new Smeared(`spc:${fixedConfig.siteId.value}/site`, true);
      await command.execute(fixedConfig, siteName);

      expect(rootMigrationMock).toHaveBeenCalledWith('root-scope-123', fixedConfig.siteId);
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('root-scope-123', externalId);
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(command['logger'].debug).toHaveBeenCalledWith(
        expect.stringMatching(/Claimed root scope root-scope-123 with externalId: .*/),
      );
    });

    it('throws when root scope migration fails', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: null,
        parentId: null,
      });
      rootMigrationMock.mockResolvedValueOnce({
        status: 'migration_failed',
        error: 'Failed to move child scopes',
      });

      await expect(command.execute(fixedConfig, siteName)).rejects.toThrow(
        'Root scope migration failed: Failed to move child scopes',
      );

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('skips claiming if externalId is already set to the correct site', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:site-123',
        parentId: null,
      });

      await command.execute(fixedConfig, siteName);

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('throws error if externalId is set to a different site', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:different-site',
        parentId: null,
      });

      await expect(command.execute(fixedConfig, siteName)).rejects.toThrow(
        /is owned by a different site/,
      );

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('grants permissions and resolves root path via the path resolver', async () => {
      const rootScope = {
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:site-123',
        parentId: 'parent-1',
      };
      getScopeByIdMock.mockResolvedValueOnce(rootScope);

      const result = await command.execute(fixedConfig, siteName);

      expect(result.serviceUserId).toBe('user-123');
      expect(result.rootScopeId).toBe('root-scope-123');
      expect(result.rootPath).toBeInstanceOf(Smeared);
      expect(result.rootPath.value).toBe('/Root/test1');
      expect(createScopeAccessesMock).toHaveBeenCalledWith('root-scope-123', [
        { type: 'MANAGE', entityId: 'user-123', entityType: 'USER' },
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
        { type: 'WRITE', entityId: 'user-123', entityType: 'USER' },
      ]);
      expect(resolveScopePathMock).toHaveBeenCalledWith(rootScope, 'user-123');
    });

    it('skips the path-walk when create-root-scope provides a precomputed path', async () => {
      const autoConfig = createMockSiteConfig({
        siteId: new Smeared('site-123', false),
        scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
      });
      const precomputedRootPath = createSmeared('/Configured/Parent/test1');
      findRootScopeMock.mockResolvedValueOnce(null);
      createRootScopeMock.mockResolvedValueOnce({
        rootScopeId: 'created-root',
        rootPath: precomputedRootPath,
      });
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'created-root',
        name: 'test1',
        externalId: 'spc:site-123/site',
        parentId: 'parent-1',
      });

      const result = await command.execute(autoConfig, siteName);

      expect(result.rootPath).toBe(precomputedRootPath);
      expect(resolveScopePathMock).not.toHaveBeenCalled();
      expect(createScopeAccessesMock).toHaveBeenCalledWith('created-root', [
        { type: 'MANAGE', entityId: 'user-123', entityType: 'USER' },
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
        { type: 'WRITE', entityId: 'user-123', entityType: 'USER' },
      ]);
    });

    it('accepts new-format root externalId as valid ownership', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site-123/site',
        parentId: null,
      });

      const result = await command.execute(fixedConfig, siteName);

      expect(result.isInitialSync).toBe(false);
      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    describe('scope externalId migration', () => {
      it('delegates the migration decision to the migration service', async () => {
        getScopeByIdMock.mockResolvedValueOnce({
          id: 'root-scope-123',
          name: 'test1',
          externalId: 'spc:site:site-123',
          parentId: null,
        });

        await command.execute(fixedConfig, siteName);

        expect(externalIdMigrationMock).toHaveBeenCalledWith('site-123');
      });

      it('throws and aborts sync when migration reports failure', async () => {
        getScopeByIdMock.mockResolvedValueOnce({
          id: 'root-scope-123',
          name: 'test1',
          externalId: 'spc:site:site-123',
          parentId: null,
        });
        externalIdMigrationMock.mockResolvedValueOnce({
          status: 'migration_failed',
          migratedCount: 3,
          failedCount: 2,
        });

        await expect(command.execute(fixedConfig, siteName)).rejects.toThrow(
          /Scope externalId migration failed.*migrated=3.*failed=2/,
        );
      });
    });
  });

  describe('auto root-scope orchestration', () => {
    const autoConfig = createMockSiteConfig({
      siteId: new Smeared('site-auto', false),
      scopeId: { type: 'auto', parentScopeId: 'scope_parent' },
    });

    beforeEach(() => {
      getScopeByIdMock.mockResolvedValue({
        id: 'root-id',
        name: 'test1',
        externalId: 'spc:site-auto/site',
        parentId: 'scope_parent',
      });
    });

    it('creates a new root scope when finder returns null', async () => {
      const createdPath = createSmeared('/created/path');
      findRootScopeMock.mockResolvedValue(null);
      createRootScopeMock.mockResolvedValue({
        rootScopeId: 'created-root',
        rootPath: createdPath,
      });
      getScopeByIdMock.mockReset();
      getScopeByIdMock.mockResolvedValue({
        id: 'created-root',
        name: 'test1',
        externalId: 'spc:site-auto/site',
        parentId: 'scope_parent',
      });

      const result = await command.execute(autoConfig, siteName);

      expect(createRootScopeMock).toHaveBeenCalledWith(autoConfig, siteName);
      expect(result.rootScopeId).toBe('created-root');
      expect(result.rootPath).toBe(createdPath);
      expect(updateScopeParentMock).not.toHaveBeenCalled();
    });

    it('reuses found scope when its parent matches the configured parent', async () => {
      findRootScopeMock.mockResolvedValue({
        id: 'found-root',
        name: 'test-site-name',
        parentId: 'scope_parent',
        externalId: 'spc:site-auto/site',
      });
      getScopeByIdMock.mockReset();
      getScopeByIdMock.mockResolvedValue({
        id: 'found-root',
        name: 'test-site-name',
        parentId: 'scope_parent',
        externalId: 'spc:site-auto/site',
      });

      const result = await command.execute(autoConfig, siteName);

      expect(createRootScopeMock).not.toHaveBeenCalled();
      expect(updateScopeParentMock).not.toHaveBeenCalled();
      expect(result.rootScopeId).toBe('found-root');
      expect(resolveScopePathMock).toHaveBeenCalled();
    });

    it('moves found scope when its parent differs from the configured parent', async () => {
      findRootScopeMock.mockResolvedValue({
        id: 'found-root',
        name: 'test-site-name',
        parentId: 'some_other_parent',
        externalId: 'spc:site-auto/site',
      });
      getScopeByIdMock.mockReset();
      getScopeByIdMock.mockResolvedValue({
        id: 'found-root',
        name: 'test-site-name',
        parentId: 'scope_parent',
        externalId: 'spc:site-auto/site',
      });

      const result = await command.execute(autoConfig, siteName);

      expect(updateScopeParentMock).toHaveBeenCalledWith('found-root', 'scope_parent');
      expect(createRootScopeMock).not.toHaveBeenCalled();
      expect(result.rootScopeId).toBe('found-root');
    });

    it('bubbles up errors thrown by the finder', async () => {
      const error = new RootScopeResolutionError('foreign_name_match', {
        siteId: 'site-auto',
        parentScopeId: 'scope_parent',
        siteName,
        detail: 'name conflict',
      });
      findRootScopeMock.mockRejectedValue(error);

      await expect(command.execute(autoConfig, siteName)).rejects.toBe(error);
      expect(createScopeAccessesMock).not.toHaveBeenCalled();
    });

    it('bubbles up errors thrown by the creator', async () => {
      findRootScopeMock.mockResolvedValue(null);
      const error = new RootScopeResolutionError('claim_failed', {
        siteId: 'site-auto',
        parentScopeId: 'scope_parent',
        siteName,
        detail: 'claim failed',
      });
      createRootScopeMock.mockRejectedValue(error);

      await expect(command.execute(autoConfig, siteName)).rejects.toBe(error);
      expect(createScopeAccessesMock).not.toHaveBeenCalled();
    });

    it('does not call finder or creator for fixed rows', async () => {
      const fixedConfig = createMockSiteConfig({
        siteId: new Smeared('site-fixed', false),
        scopeId: { type: 'fixed', scopeId: 'scope_fixed' },
      });
      getScopeByIdMock.mockReset();
      getScopeByIdMock.mockResolvedValue({
        id: 'scope_fixed',
        name: 'test1',
        externalId: 'spc:site-fixed/site',
        parentId: 'parent-1',
      });

      await command.execute(fixedConfig, siteName);

      expect(findRootScopeMock).not.toHaveBeenCalled();
      expect(createRootScopeMock).not.toHaveBeenCalled();
    });
  });
});
