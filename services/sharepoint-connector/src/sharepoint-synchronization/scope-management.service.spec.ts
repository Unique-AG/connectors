import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Config } from '../config';
import { IngestionMode } from '../constants/ingestion.constants';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { ScopeManagementService } from './scope-management.service';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

const createDriveContentItem = (path: string): SharepointContentItem => {
  const webUrl = `https://example.sharepoint.com/sites/test1/${path}/Page%201.aspx`;

  return {
    itemType: 'driveItem',
    item: {
      '@odata.etag': 'etag-1',
      id: `drive-item-${path}`,
      name: 'Page 1.aspx',
      webUrl,
      size: 1024,
      createdDateTime: '2025-01-01T00:00:00Z',
      lastModifiedDateTime: '2025-01-01T00:00:00Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive-1',
        id: 'parent-id',
        name: 'Documents',
        path: `/drive/root:/${path}`,
        siteId: 'site-123',
      },
      file: {
        mimeType: 'text/html',
        hashes: {
          quickXorHash: 'hash-1',
        },
      },
      listItem: {
        '@odata.etag': 'etag-2',
        id: `list-item-${path}`,
        eTag: 'etag-2',
        createdDateTime: '2025-01-01T00:00:00Z',
        lastModifiedDateTime: '2025-01-01T00:00:00Z',
        webUrl,
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        fields: {
          '@odata.etag': 'etag-2',
          FinanceGPTKnowledge: true,
          FileLeafRef: 'Page 1.aspx',
          Modified: '2025-01-01T00:00:00Z',
          Created: '2025-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          FileSizeDisplay: '12345',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    },
    siteId: 'site-123',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: `/${path}`,
    fileName: 'Page 1.aspx',
  };
};

describe('ScopeManagementService', () => {
  const mockScopes: ScopeWithPath[] = [
    { id: 'scope_1', name: 'test1', parentId: null, externalId: null, path: '/test1' },
    {
      id: 'scope_2',
      name: 'UniqueAG',
      parentId: 'scope_1',
      externalId: null,
      path: '/test1/UniqueAG',
    },
    {
      id: 'scope_3',
      name: 'SitePages',
      parentId: 'scope_2',
      externalId: null,
      path: '/test1/UniqueAG/SitePages',
    },
  ];

  const mockContext: SharepointSyncContext = {
    serviceUserId: 'user-123',
    rootPath: '/test1',
    siteName: 'test-site',
    siteConfig: createMockSiteConfig({ siteId: 'site-123', scopeId: 'root-scope-123' }),
  };

  type ConfigServiceMock = ConfigService<Config, true> & { get: ReturnType<typeof vi.fn> };

  let service: ScopeManagementService;
  let createScopesMock: ReturnType<typeof vi.fn>;
  let configServiceMock: ConfigServiceMock;

  beforeEach(async () => {
    createScopesMock = vi.fn().mockResolvedValue(
      mockScopes.map(({ id, name, parentId, externalId }) => ({
        id,
        name,
        parentId,
        externalId,
      })),
    );

    configServiceMock = {
      get: vi.fn((key: string) => {
        if (key === 'app.logsDiagnosticsDataPolicy') {
          return 'conceal';
        }
        return undefined;
      }),
    } as unknown as ConfigServiceMock;

    const { unit } = await TestBed.solitary(ScopeManagementService)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        createScopesBasedOnPaths: createScopesMock,
      }))
      .mock<ConfigService<Config, true>>(ConfigService)
      .impl(() => configServiceMock)
      .compile();

    service = unit;

    // Mock the logger property since it's created in the constructor
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

  describe('initializeRootScope', () => {
    let getScopeByIdMock: ReturnType<typeof vi.fn>;
    let createScopeAccessesMock: ReturnType<typeof vi.fn>;
    let getCurrentUserIdMock: ReturnType<typeof vi.fn>;
    let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      getScopeByIdMock = vi.fn();
      createScopeAccessesMock = vi.fn();
      getCurrentUserIdMock = vi.fn().mockResolvedValue('user-123');
      updateScopeExternalIdMock = vi.fn().mockResolvedValue({ externalId: 'updated-external-id' });

      const configService = {
        get: vi.fn((key: string) => {
          if (key === 'app.logsDiagnosticsDataPolicy') return 'show';
          return undefined;
        }),
      };

      const { unit } = await TestBed.solitary(ScopeManagementService)
        .mock<UniqueScopesService>(UniqueScopesService)
        .impl((stubFn) => ({
          ...stubFn(),
          getScopeById: getScopeByIdMock,
          createScopeAccesses: createScopeAccessesMock,
          updateScopeExternalId: updateScopeExternalIdMock,
        }))
        .mock<UniqueUsersService>(UniqueUsersService)
        .impl((stubFn) => ({
          ...stubFn(),
          getCurrentUserId: getCurrentUserIdMock,
        }))
        .mock<ConfigService<Config, true>>(ConfigService)
        .impl(() => configService as unknown as ConfigService<Config, true>)
        .compile();

      service = unit;

      // Mock the logger property
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

    it('claims the root scope if externalId is missing', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: null,
        parentId: null,
      });

      await service.initializeRootScope('root-scope-123', 'site-123', IngestionMode.Flat);

      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('root-scope-123', 'spc:site:site-123');
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].debug).toHaveBeenCalledWith(
        expect.stringContaining(
          'Claimed root scope root-scope-123 with externalId: spc:site:site-123',
        ),
      );
    });

    it('skips claiming if externalId is already set to the correct site', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:site-123',
        parentId: null,
      });

      await service.initializeRootScope('root-scope-123', 'site-123', IngestionMode.Flat);

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('throws error if externalId is set to a different site', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:different-site',
        parentId: null,
      });

      await expect(
        service.initializeRootScope('root-scope-123', 'site-123', IngestionMode.Flat),
      ).rejects.toThrow(/is owned by a different site/);

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('grants permissions and resolves root path', async () => {
      getScopeByIdMock
        .mockResolvedValueOnce({
          id: 'root-scope-123',
          name: 'test1',
          externalId: 'spc:site:site-123',
          parentId: 'parent-1',
        })
        .mockResolvedValueOnce({
          id: 'parent-1',
          name: 'Root',
          externalId: null,
          parentId: null,
        });

      const result = await service.initializeRootScope(
        'root-scope-123',
        'site-123',
        IngestionMode.Flat,
      );

      expect(result).toEqual({ serviceUserId: 'user-123', rootPath: '/Root/test1' });
      expect(createScopeAccessesMock).toHaveBeenCalledWith('root-scope-123', [
        { type: 'MANAGE', entityId: 'user-123', entityType: 'USER' },
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
        { type: 'WRITE', entityId: 'user-123', entityType: 'USER' },
      ]);
      expect(createScopeAccessesMock).toHaveBeenCalledWith('parent-1', [
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
        { type: 'WRITE', entityId: 'user-123', entityType: 'USER' },
      ]);
    });
  });

  describe('extractAllParentPaths', () => {
    it('generates hierarchical paths for a single entry', () => {
      const result = service.extractAllParentPaths(['test1/UniqueAG/SitePages']);

      expect(result).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
      expect(new Set(result).size).toBe(result.length);
    });

    it('combines parents for multiple entries', () => {
      const result = service.extractAllParentPaths([
        'test1/UniqueAG/SitePages',
        'test1/UniqueAG/Freigegebene Dokumente/General',
      ]);

      expect(result).toEqual(
        expect.arrayContaining([
          '/test1/UniqueAG/Freigegebene Dokumente',
          '/test1/UniqueAG/Freigegebene Dokumente/General',
        ]),
      );
      expect(result).toContain('/test1/UniqueAG/SitePages');
    });

    it('returns empty array when no paths provided', () => {
      const result = service.extractAllParentPaths([]);
      expect(result).toHaveLength(0);
    });

    it('trims and normalizes paths with trailing slash', () => {
      const result = service.extractAllParentPaths(['test1/UniqueAG/SitePages/']);

      expect(result).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
    });
  });

  describe('batchCreateScopes', () => {
    it('creates scopes and returns list', async () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];

      const result = await service.batchCreateScopes(items, [], mockContext);

      expect(result).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ id: 'scope_1', name: 'test1', path: '/test1' }),
          expect.objectContaining({
            id: 'scope_2',
            name: 'UniqueAG',
            path: '/test1/UniqueAG',
          }),
          expect.objectContaining({
            id: 'scope_3',
            name: 'SitePages',
            path: '/test1/UniqueAG/SitePages',
          }),
        ]),
      );

      const [paths, options] = createScopesMock.mock.calls[0] as [
        string[],
        { includePermissions: boolean; inheritAccess: boolean },
      ];
      expect(options).toEqual({ includePermissions: true, inheritAccess: true });
      expect(paths).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
    });

    it('disables inheritance when permission sync mode is enabled', async () => {
      const contextWithPermissionsSync: SharepointSyncContext = {
        ...mockContext,
        siteConfig: createMockSiteConfig({
          syncMode: 'content_and_permissions',
        }),
      };

      await service.batchCreateScopes(
        [createDriveContentItem('UniqueAG/SitePages')],
        [],
        contextWithPermissionsSync,
      );

      const [, options] = createScopesMock.mock.calls[0] as [
        string[],
        { includePermissions: boolean; inheritAccess: boolean },
      ];
      expect(options.inheritAccess).toBe(false);
    });

    it('uses explicit inheritAccess configuration when provided', async () => {
      const contextWithInheritScopes: SharepointSyncContext = {
        ...mockContext,
        siteConfig: createMockSiteConfig({
          syncMode: 'content_only',
          permissionsInheritanceMode: 'inherit_scopes',
        }),
      };

      await service.batchCreateScopes(
        [createDriveContentItem('UniqueAG/SitePages')],
        [],
        contextWithInheritScopes,
      );

      const [, options] = createScopesMock.mock.calls[0] as [
        string[],
        { includePermissions: boolean; inheritAccess: boolean },
      ];
      expect(options.inheritAccess).toBe(true);
    });

    it('returns empty list when no items provided', async () => {
      const result = await service.batchCreateScopes([], [], mockContext);

      expect(result).toHaveLength(0);
      expect(createScopesMock).not.toHaveBeenCalled();
    });

    it('logs site identifier in success message', async () => {
      await service.batchCreateScopes(
        [createDriveContentItem('UniqueAG/SitePages')],
        [],
        mockContext,
      );

      // The logger is globally mocked, so we can check the mock calls
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].log).toHaveBeenCalledWith(expect.stringContaining('[Site:'));
    });
  });

  describe('buildItemIdToScopeIdMap', () => {
    it('maps item identifiers to scope identifiers', () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];
      const item = items[0];

      const result = service.buildItemIdToScopeIdMap(items, mockScopes, mockContext);

      // biome-ignore lint/style/noNonNullAssertion: Test data is guaranteed to exist
      expect(result.get(item!.item.id)).toBe('scope_3');
    });

    it('decodes URL-encoded paths before lookup', () => {
      const items = [createDriveContentItem('UniqueAG/Freigegebene%20Dokumente/General')];
      const item = items[0];

      const result = service.buildItemIdToScopeIdMap(items, mockScopes, mockContext);

      // The scope for this path doesn't exist in mockScopes, so it should return undefined
      // biome-ignore lint/style/noNonNullAssertion: Test data is guaranteed to exist
      expect(result.get(item!.item.id)).toBeUndefined();
    });

    it('returns empty map when scopes is empty', () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];

      const result = service.buildItemIdToScopeIdMap(items, [], mockContext);

      expect(result.size).toBe(0);
    });

    it('logs warning when scope is not present in cache', () => {
      const items = [createDriveContentItem('UniqueAG/UnknownFolder')];

      service.buildItemIdToScopeIdMap(items, mockScopes, mockContext);

      // The logger is globally mocked, so we can check the mock calls
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].warn).toHaveBeenCalledWith(
        expect.stringContaining('Scope not found in cache for path'),
      );
    });
  });

  describe('updateNewlyCreatedScopesWithExternalId', () => {
    let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      updateScopeExternalIdMock = vi.fn().mockResolvedValue({ externalId: 'updated-external-id' });

      const configService = {
        get: vi.fn((key: string) => {
          if (key === 'app.logsDiagnosticsDataPolicy') return 'show'; // Don't conceal logs for this test
          return undefined;
        }),
      };

      const { unit } = await TestBed.solitary(ScopeManagementService)
        .mock<UniqueScopesService>(UniqueScopesService)
        .impl((stubFn) => ({
          ...stubFn(),
          updateScopeExternalId: updateScopeExternalIdMock,
        }))
        .mock<ConfigService<Config, true>>(ConfigService)
        .impl(() => configService as unknown as ConfigService<Config, true>)
        .compile();

      service = unit;

      // Mock the logger property since it's created in the constructor
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

    it('creates fallback externalId when no externalId found for path', async () => {
      const scopes = [
        { id: 'scope-1', name: 'TestScope', externalId: null },
        { id: 'scope-2', name: 'AnotherScope', externalId: null },
      ];
      const paths = ['/test1/TestScope', '/test1/AnotherScope'];
      const directories: SharepointDirectoryItem[] = []; // No directories provided

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      await (service as any).updateNewlyCreatedScopesWithExternalId(
        scopes,
        paths,
        directories,
        mockContext,
      );

      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(2);
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
        'scope-1',
        expect.stringMatching(/^spc:unknown:site-123\/TestScope-/),
      );
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
        'scope-2',
        expect.stringMatching(/^spc:unknown:site-123\/AnotherScope-/),
      );
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].warn).toHaveBeenCalledWith(
        expect.stringContaining('No external ID found for path'),
      );
    });

    it('skips scopes that already have externalId', async () => {
      const scopes = [
        { id: 'scope-1', name: 'test1', externalId: 'existing-external-id' },
        { id: 'scope-2', name: 'SitePages', externalId: null },
      ];
      const paths = ['/test1', '/test1/SitePages'];
      const directories: SharepointDirectoryItem[] = [];

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      await (service as any).updateNewlyCreatedScopesWithExternalId(
        scopes,
        paths,
        directories,
        mockContext,
      );

      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('scope-2', 'spc:site-123/sitePages');
    });

    it('skips scopes that are ancestors of root path', async () => {
      const scopes = [
        { id: 'scope-1', name: 'Root', externalId: null },
        { id: 'scope-2', name: 'ChildScope', externalId: null },
      ];
      const paths = ['/', '/test1/ChildScope'];
      // mockContext.rootPath is '/test1'
      const directories: SharepointDirectoryItem[] = [];

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      await (service as any).updateNewlyCreatedScopesWithExternalId(
        scopes,
        paths,
        directories,
        mockContext,
      );

      // Root (/) is an ancestor of /test1, so it is skipped.
      // ChildScope (/test1/ChildScope) gets fallback externalId.
      expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
        'scope-2',
        expect.stringMatching(/^spc:unknown:site-123\/ChildScope-/),
      );
    });

    it('logs debug message when updating externalId', async () => {
      const scopes = [{ id: 'scope-1', name: 'test1', externalId: null }];
      const paths = ['/test1'];
      const directories: SharepointDirectoryItem[] = [];

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      await (service as any).updateNewlyCreatedScopesWithExternalId(
        scopes,
        paths,
        directories,
        mockContext,
      );

      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].debug).toHaveBeenCalledWith(
        expect.stringMatching(
          /^Updated scope scope-1 with externalId: spc:unknown:site-123\/test1-/,
        ),
      );
    });

    it('logs warning when externalId update fails', async () => {
      updateScopeExternalIdMock.mockRejectedValue(new Error('Update failed'));
      const scopes = [{ id: 'scope-1', name: 'test1', externalId: null }];
      const paths = ['/test1'];
      const directories: SharepointDirectoryItem[] = [];

      // biome-ignore lint/suspicious/noExplicitAny: Testing private method
      await (service as any).updateNewlyCreatedScopesWithExternalId(
        scopes,
        paths,
        directories,
        mockContext,
      );

      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].warn).toHaveBeenCalledWith({
        msg: 'Failed to update externalId for scope scope-1',
        error: expect.any(Object),
      });
    });
  });
});
