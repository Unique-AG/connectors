import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestionMode } from '../constants/ingestion.constants';
import type {
  SharepointContentItem,
  SharepointDirectoryItem,
} from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope, ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { UniqueUsersService } from '../unique-api/unique-users/unique-users.service';
import { Smeared } from '../utils/smeared';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { RootScopeMigrationService } from './root-scope-migration.service';
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
    siteId: new Smeared('site-123', false),
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
    rootPath: new Smeared('/test1', false),
    siteName: new Smeared('test-site', false),
    siteConfig: createMockSiteConfig({
      siteId: new Smeared('site-123', false),
      scopeId: 'root-scope-123',
    }),
    isInitialSync: false,
    discoveredSubsites: [],
  };

  let service: ScopeManagementService;
  let createScopesMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    createScopesMock = vi.fn().mockResolvedValue(
      mockScopes.map(({ id, name, parentId, externalId }) => ({
        id,
        name,
        parentId,
        externalId,
      })),
    );

    const { unit } = await TestBed.solitary(ScopeManagementService)
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        createScopesBasedOnPaths: createScopesMock,
      }))
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
    let migrateIfNeededMock: ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      getScopeByIdMock = vi.fn();
      createScopeAccessesMock = vi.fn();
      getCurrentUserIdMock = vi.fn().mockResolvedValue('user-123');
      updateScopeExternalIdMock = vi.fn().mockResolvedValue({ externalId: 'updated-external-id' });
      migrateIfNeededMock = vi.fn().mockResolvedValue({ status: 'no_migration_needed' });

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
        .mock<RootScopeMigrationService>(RootScopeMigrationService)
        .impl((stubFn) => ({
          ...stubFn(),
          migrateIfNeeded: migrateIfNeededMock,
        }))
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

      const siteId = new Smeared('site-123', false);
      // As we do not patch env variable, Smeared external id constructed inside will be active.
      const externalId = new Smeared(`spc:site:${siteId.value}`, true);
      await service.initializeRootScope('root-scope-123', siteId, IngestionMode.Flat);

      expect(migrateIfNeededMock).toHaveBeenCalledWith('root-scope-123', siteId);
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('root-scope-123', externalId);
      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].debug).toHaveBeenCalledWith(
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
      migrateIfNeededMock.mockResolvedValueOnce({
        status: 'migration_failed',
        error: 'Failed to move child scopes',
      });

      await expect(
        service.initializeRootScope(
          'root-scope-123',
          new Smeared('site-123', false),
          IngestionMode.Flat,
        ),
      ).rejects.toThrow('Root scope migration failed: Failed to move child scopes');

      expect(updateScopeExternalIdMock).not.toHaveBeenCalled();
    });

    it('skips claiming if externalId is already set to the correct site', async () => {
      getScopeByIdMock.mockResolvedValueOnce({
        id: 'root-scope-123',
        name: 'test1',
        externalId: 'spc:site:site-123',
        parentId: null,
      });

      await service.initializeRootScope(
        'root-scope-123',
        new Smeared('site-123', false),
        IngestionMode.Flat,
      );

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
        service.initializeRootScope(
          'root-scope-123',
          new Smeared('site-123', false),
          IngestionMode.Flat,
        ),
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
        new Smeared('site-123', false),
        IngestionMode.Flat,
      );

      expect(result.serviceUserId).toBe('user-123');
      expect(result.rootPath).toBeInstanceOf(Smeared);
      expect(result.rootPath.value).toBe('/Root/test1');
      expect(createScopeAccessesMock).toHaveBeenCalledWith('root-scope-123', [
        { type: 'MANAGE', entityId: 'user-123', entityType: 'USER' },
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
        { type: 'WRITE', entityId: 'user-123', entityType: 'USER' },
      ]);
      expect(createScopeAccessesMock).toHaveBeenCalledWith('parent-1', [
        { type: 'READ', entityId: 'user-123', entityType: 'USER' },
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

    describe('subsite external ID assignment', () => {
      let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;

      const makeSubsite = (name: string, relativePath: string, siteId: string) => ({
        siteId: new Smeared(siteId, false),
        name: new Smeared(name, false),
        relativePath: new Smeared(relativePath, false),
      });

      const createSubsiteContentItem = (path: string, siteId: string): SharepointContentItem => {
        const item = createDriveContentItem(path);
        return {
          ...item,
          siteId: new Smeared(siteId, false),
          syncSiteId: new Smeared('site-123', false),
        };
      };

      const createSubsiteDirectoryItem = (
        webUrl: string,
        siteId: string,
        driveId: string,
        folderId: string,
      ): SharepointDirectoryItem =>
        ({
          itemType: 'directory',
          siteId: new Smeared(siteId, false),
          syncSiteId: new Smeared('site-123', false),
          driveId,
          driveName: 'Documents',
          folderPath: '/path',
          fileName: '',
          item: {
            id: folderId,
            webUrl,
            listItem: {
              webUrl: '',
              id: 'li-1',
              '@odata.etag': 'e',
              eTag: 'e',
              createdDateTime: '2025-01-01T00:00:00Z',
              lastModifiedDateTime: '2025-01-01T00:00:00Z',
              fields: {},
            },
          },
        }) as SharepointDirectoryItem;

      beforeEach(async () => {
        updateScopeExternalIdMock = vi
          .fn()
          .mockResolvedValue({ externalId: 'updated-external-id' });

        const { unit } = await TestBed.solitary(ScopeManagementService)
          .mock<UniqueScopesService>(UniqueScopesService)
          .impl((stubFn) => ({
            ...stubFn(),
            createScopesBasedOnPaths: vi.fn().mockImplementation((paths: string[]) =>
              paths.map((path, i) => ({
                id: `scope-${i}`,
                name: path.split('/').pop(),
                parentId: null,
                externalId: null,
              })),
            ),
            updateScopeExternalId: updateScopeExternalIdMock,
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

      it('assigns subsite: and drive: for subsite directories', async () => {
        const subASiteId = 'host.com,col-a,web-a';
        const context: SharepointSyncContext = {
          ...mockContext,
          discoveredSubsites: [makeSubsite('SubA', 'SubA', subASiteId)],
        };
        const item = createSubsiteContentItem('SubA/Documents/Reports', subASiteId);
        const directory = createSubsiteDirectoryItem(
          'https://example.sharepoint.com/sites/test1/SubA/Documents/Reports',
          subASiteId,
          'sub-drive',
          'sub-folder',
        );

        await service.batchCreateScopes([item], [directory], context);

        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:subsite:${subASiteId}` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:drive:${subASiteId}/sub-drive` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:folder:${subASiteId}/sub-folder` }),
        );
      });

      it('strips nested subsite prefix so drive is correctly identified', async () => {
        const subASiteId = 'host.com,a1,a2';
        const subBSiteId = 'host.com,b1,b2';
        const context: SharepointSyncContext = {
          ...mockContext,
          discoveredSubsites: [
            makeSubsite('SubA', 'SubA', subASiteId),
            makeSubsite('SubB', 'SubA/SubB', subBSiteId),
          ],
        };
        const item = createSubsiteContentItem('SubA/SubB/Docs/Archive', subBSiteId);
        const directory = createSubsiteDirectoryItem(
          'https://example.sharepoint.com/sites/test1/SubA/SubB/Docs/Archive',
          subBSiteId,
          'nested-drive',
          'nested-folder',
        );

        await service.batchCreateScopes([item], [directory], context);

        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:subsite:${subASiteId}` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:subsite:${subBSiteId}` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:drive:${subBSiteId}/nested-drive` }),
        );
      });

      it('assigns correct IDs for both root-site and subsite directories together', async () => {
        const subASiteId = 'host.com,col-a,web-a';
        const context: SharepointSyncContext = {
          ...mockContext,
          discoveredSubsites: [makeSubsite('SubA', 'SubA', subASiteId)],
        };
        const rootItem = createDriveContentItem('Documents/Folder1');
        const rootDirectory: SharepointDirectoryItem = {
          itemType: 'directory',
          siteId: new Smeared('site-123', false),
          driveId: 'root-drive',
          driveName: 'Documents',
          folderPath: '/Documents/Folder1',
          fileName: '',
          item: {
            id: 'root-folder',
            webUrl: 'https://example.sharepoint.com/sites/test1/Documents/Folder1',
          },
        } as SharepointDirectoryItem;
        const subsiteItem = createSubsiteContentItem('SubA/Docs/Reports', subASiteId);
        const subsiteDirectory = createSubsiteDirectoryItem(
          'https://example.sharepoint.com/sites/test1/SubA/Docs/Reports',
          subASiteId,
          'sub-drive',
          'sub-folder',
        );

        await service.batchCreateScopes(
          [rootItem, subsiteItem],
          [rootDirectory, subsiteDirectory],
          context,
        );

        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: 'spc:drive:site-123/root-drive' }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: 'spc:folder:site-123/root-folder' }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:subsite:${subASiteId}` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:drive:${subASiteId}/sub-drive` }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({ value: `spc:folder:${subASiteId}/sub-folder` }),
        );
      });
    });
  });

  describe('updateNewlyCreatedScopesWithExternalId', () => {
    let updateScopeExternalIdMock: ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      updateScopeExternalIdMock = vi.fn().mockResolvedValue({ externalId: 'updated-external-id' });

      const { unit } = await TestBed.solitary(ScopeManagementService)
        .mock<UniqueScopesService>(UniqueScopesService)
        .impl((stubFn) => ({
          ...stubFn(),
          updateScopeExternalId: updateScopeExternalIdMock,
        }))
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
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('scope-1', expect.any(Smeared));
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('scope-2', expect.any(Smeared));
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
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('scope-2', expect.any(Smeared));
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
      expect(updateScopeExternalIdMock).toHaveBeenCalledWith('scope-2', expect.any(Smeared));
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
        expect.stringMatching(/^Updated scope scope-1 with externalId: .*/),
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

    describe('conflict marking', () => {
      let getScopeByExternalIdMock: ReturnType<typeof vi.fn>;

      beforeEach(async () => {
        getScopeByExternalIdMock = vi.fn().mockResolvedValue(null);
        updateScopeExternalIdMock = vi
          .fn()
          .mockResolvedValue({ externalId: 'updated-external-id' });

        const { unit } = await TestBed.solitary(ScopeManagementService)
          .mock<UniqueScopesService>(UniqueScopesService)
          .impl((stubFn) => ({
            ...stubFn(),
            updateScopeExternalId: updateScopeExternalIdMock,
            getScopeByExternalId: getScopeByExternalIdMock,
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

      it('marks conflicting scope with pending-delete prefix and assigns externalId to new scope', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-scope-id',
          name: 'OldScope',
          parentId: null,
          externalId: 'spc:folder:site-123/folder-1',
        });

        const scopes = [{ id: 'new-scope-id', name: 'TestScope', externalId: null }];
        const paths = ['/test1/TestScope'];
        const directories: SharepointDirectoryItem[] = [];

        // biome-ignore lint/suspicious/noExplicitAny: Testing private method
        await (service as any).updateNewlyCreatedScopesWithExternalId(
          scopes,
          paths,
          directories,
          mockContext,
        );

        expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(2);

        const [renameId, renameExternalId] = updateScopeExternalIdMock.mock.calls[0] as [
          string,
          Smeared,
        ];
        expect(renameId).toBe('old-scope-id');
        expect(renameExternalId).toBeInstanceOf(Smeared);
        expect(renameExternalId.value).toMatch(
          /^spc:pending-delete:site-123\/unknown:site-123\/TestScope-/,
        );

        expect(updateScopeExternalIdMock).toHaveBeenNthCalledWith(
          2,
          'new-scope-id',
          expect.any(Smeared),
        );
      });

      it('proceeds without marking when no conflicting scope exists', async () => {
        getScopeByExternalIdMock.mockResolvedValue(null);

        const scopes = [{ id: 'new-scope-id', name: 'TestScope', externalId: null }];
        const paths = ['/test1/TestScope'];
        const directories: SharepointDirectoryItem[] = [];

        // biome-ignore lint/suspicious/noExplicitAny: Testing private method
        await (service as any).updateNewlyCreatedScopesWithExternalId(
          scopes,
          paths,
          directories,
          mockContext,
        );

        expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith('new-scope-id', expect.any(Smeared));
      });

      it('logs warning and still updates new scope when marking conflicting scope fails', async () => {
        getScopeByExternalIdMock.mockResolvedValue({
          id: 'old-scope-id',
          name: 'OldScope',
          parentId: null,
          externalId: 'spc:folder:site-123/folder-1',
        });

        updateScopeExternalIdMock
          .mockRejectedValueOnce(new Error('Rename failed'))
          .mockResolvedValue({ externalId: 'updated-external-id' });

        const scopes = [{ id: 'new-scope-id', name: 'TestScope', externalId: null }];
        const paths = ['/test1/TestScope'];
        const directories: SharepointDirectoryItem[] = [];

        // biome-ignore lint/suspicious/noExplicitAny: Testing private method
        await (service as any).updateNewlyCreatedScopesWithExternalId(
          scopes,
          paths,
          directories,
          mockContext,
        );

        // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
        expect(service['logger'].warn).toHaveBeenCalledWith(
          expect.objectContaining({
            msg: expect.stringContaining('Failed to mark conflicting scope'),
          }),
        );
        expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(2);
        expect(updateScopeExternalIdMock).toHaveBeenLastCalledWith(
          'new-scope-id',
          expect.any(Smeared),
        );
      });

      it('skips conflict marking during initial sync', async () => {
        const initialSyncContext = { ...mockContext, isInitialSync: true };
        const scopes = [{ id: 'new-scope-id', name: 'TestScope', externalId: null }];
        const paths = ['/test1/TestScope'];
        const directories: SharepointDirectoryItem[] = [];

        // biome-ignore lint/suspicious/noExplicitAny: Testing private method
        await (service as any).updateNewlyCreatedScopesWithExternalId(
          scopes,
          paths,
          directories,
          initialSyncContext,
        );

        expect(getScopeByExternalIdMock).not.toHaveBeenCalled();
        expect(updateScopeExternalIdMock).toHaveBeenCalledTimes(1);
        expect(updateScopeExternalIdMock).toHaveBeenCalledWith('new-scope-id', expect.any(Smeared));
      });
    });
  });

  describe('deleteOrphanedScopes', () => {
    let listScopesByExternalIdPrefixMock: ReturnType<typeof vi.fn>;
    let deleteScopeMock: ReturnType<typeof vi.fn>;

    beforeEach(async () => {
      listScopesByExternalIdPrefixMock = vi.fn().mockResolvedValue([]);
      deleteScopeMock = vi.fn().mockResolvedValue(undefined);

      const { unit } = await TestBed.solitary(ScopeManagementService)
        .mock<UniqueScopesService>(UniqueScopesService)
        .impl((stubFn) => ({
          ...stubFn(),
          listScopesByExternalIdPrefix: listScopesByExternalIdPrefixMock,
          deleteScope: deleteScopeMock,
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

    it('deletes orphaned scopes children-first', async () => {
      const parentScope: Scope = {
        id: 'parent-scope',
        name: 'Parent',
        parentId: null,
        externalId: 'spc:pending-delete:site-123/folder-parent',
      };
      const childScope: Scope = {
        id: 'child-scope',
        name: 'Child',
        parentId: 'parent-scope',
        externalId: 'spc:pending-delete:site-123/folder-child',
      };
      listScopesByExternalIdPrefixMock.mockResolvedValue([parentScope, childScope]);

      await service.deleteOrphanedScopes(new Smeared('site-123', false));

      expect(listScopesByExternalIdPrefixMock).toHaveBeenCalledWith(
        expect.objectContaining({
          value: 'spc:pending-delete:site-123/',
        }),
      );
      expect(deleteScopeMock).toHaveBeenCalledTimes(2);
      expect(deleteScopeMock).toHaveBeenNthCalledWith(1, 'child-scope');
      expect(deleteScopeMock).toHaveBeenNthCalledWith(2, 'parent-scope');
    });

    it('logs warning and continues deleting remaining scopes when a deletion fails', async () => {
      const parentScope: Scope = {
        id: 'parent-scope',
        name: 'Parent',
        parentId: null,
        externalId: 'spc:pending-delete:site-123/folder-parent',
      };
      const childScope: Scope = {
        id: 'child-scope',
        name: 'Child',
        parentId: 'parent-scope',
        externalId: 'spc:pending-delete:site-123/folder-child',
      };
      listScopesByExternalIdPrefixMock.mockResolvedValue([parentScope, childScope]);
      deleteScopeMock
        .mockRejectedValueOnce(new Error('Delete failed'))
        .mockResolvedValue(undefined);

      await service.deleteOrphanedScopes(new Smeared('site-123', false));

      // biome-ignore lint/complexity/useLiteralKeys: Accessing private logger for testing
      expect(service['logger'].warn).toHaveBeenCalledWith(
        expect.objectContaining({
          msg: expect.stringContaining('Failed to delete orphaned scope child-scope'),
        }),
      );
      expect(deleteScopeMock).toHaveBeenCalledTimes(2);
      expect(deleteScopeMock).toHaveBeenNthCalledWith(2, 'parent-scope');
    });
  });
});
