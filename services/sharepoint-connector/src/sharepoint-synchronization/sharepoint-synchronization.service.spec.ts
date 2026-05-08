import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../constants/moderation-status.constants';
import { SiteSyncStep } from '../constants/sync-step.enum';
import { SPC_SYNC_DURATION_SECONDS } from '../metrics';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { SitesConfigurationService } from '../microsoft-apis/graph/sites-configuration.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import { createSmeared, Smeared } from '../utils/smeared';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { ContentSyncService } from './content-sync.service';
import { DeduplicateSitesQuery } from './deduplicate-sites.query';
import { FindRootScopeQuery } from './root-scope/find-root-scope.query';
import { InitializeRootScopeCommand } from './root-scope/initialize-root-scope.command';
import { RootScopeResolutionError } from './root-scope/root-scope-resolution.error';
import { ScopeManagementService } from './scope-management.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';
import { SubsiteDiscoveryService } from './subsite-discovery.service';

describe('SharepointSynchronizationService', () => {
  let service: SharepointSynchronizationService;
  let mockGraphApiService: Partial<GraphApiService>;
  let mockSitesConfigurationService: Partial<SitesConfigurationService>;
  let mockContentSyncService: {
    syncContentForSite: ReturnType<typeof vi.fn>;
  };
  let mockPermissionsSyncService: {
    syncPermissionsForSite: ReturnType<typeof vi.fn>;
  };
  let mockScopeManagementService: {
    batchCreateScopes: ReturnType<typeof vi.fn>;
    resetRootScope: ReturnType<typeof vi.fn>;
    deleteStaleScopes: ReturnType<typeof vi.fn>;
  };
  let mockSubsiteDiscoveryService: {
    discoverAllSubsites: ReturnType<typeof vi.fn>;
  };
  let mockInitializeRootScopeCommand: {
    execute: ReturnType<typeof vi.fn>;
  };
  let mockDeduplicateSitesQuery: {
    execute: ReturnType<typeof vi.fn>;
  };
  let mockFindRootScopeQuery: {
    execute: ReturnType<typeof vi.fn>;
  };
  let mockUniqueScopesService: {
    getScopeById: ReturnType<typeof vi.fn>;
    deleteScope: ReturnType<typeof vi.fn>;
  };
  let mockUniqueFilesService: {
    deleteFilesBySiteId: ReturnType<typeof vi.fn>;
  };

  const mockFile: SharepointContentItem = {
    itemType: 'driveItem',
    item: {
      '@odata.etag': 'etag1',
      id: '01JWNC3IKFO6XBRCRFWRHKJ77NAYYM3NTX',
      name: '1173246.pdf',
      webUrl:
        'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/1173246.pdf',
      size: 2178118,
      createdDateTime: '2025-10-02T00:00:00Z',
      lastModifiedDateTime: '2025-10-10T13:59:12Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
      parentReference: {
        driveType: 'documentLibrary',
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
        driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
        id: 'parent1',
        name: 'Documents',
        path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
      },
      file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
      listItem: {
        '@odata.etag': 'etag1',
        id: 'item1',
        eTag: 'etag1',
        createdDateTime: '2025-10-10T13:59:12Z',
        lastModifiedDateTime: '2025-10-10T13:59:12Z',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/1173246.pdf',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        fields: {
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          FileLeafRef: '1173246.pdf',
          Modified: '2025-10-10T13:59:12Z',
          Created: '2025-10-02T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          ItemChildCount: '0',
          FolderChildCount: '0',
          _ModerationStatus: ModerationStatus.Approved,
          FileSizeDisplay: '2178118',
        },
      },
    },
    siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
    driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    driveName: 'Documents',
    folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
    fileName: '1173246.pdf',
  };

  beforeEach(async () => {
    mockGraphApiService = {
      getAllSiteItems: vi.fn().mockResolvedValue({ items: [mockFile], directories: [] }),
      getSiteInfo: vi.fn().mockResolvedValue({
        siteName: new Smeared('test-site-name', false),
        managedPath: 'sites',
      }),
    };

    mockSitesConfigurationService = {
      loadSitesConfiguration: vi.fn().mockResolvedValue([
        createMockSiteConfig({
          siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
        }),
      ]),
      fetchSitesFromSharePointList: vi.fn().mockResolvedValue([
        createMockSiteConfig({
          siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
        }),
      ]),
    };

    mockContentSyncService = {
      syncContentForSite: vi.fn().mockResolvedValue(undefined),
    };

    mockPermissionsSyncService = {
      syncPermissionsForSite: vi.fn().mockResolvedValue(undefined),
    };

    mockScopeManagementService = {
      batchCreateScopes: vi.fn().mockResolvedValue([]),
      resetRootScope: vi.fn().mockResolvedValue(undefined),
      deleteStaleScopes: vi.fn().mockResolvedValue(undefined),
    };

    mockSubsiteDiscoveryService = {
      discoverAllSubsites: vi.fn().mockResolvedValue([]),
    };

    mockInitializeRootScopeCommand = {
      execute: vi
        .fn()
        .mockImplementation(
          async (siteConfig: { scopeId: { type: string; scopeId?: string } }) => ({
            rootScopeId:
              siteConfig.scopeId.type === 'fixed'
                ? (siteConfig.scopeId.scopeId ?? 'fallback')
                : 'auto-root',
            serviceUserId: 'user-123',
            rootPath: new Smeared('/test-root', false),
            isInitialSync: false,
          }),
        ),
    };

    mockDeduplicateSitesQuery = {
      execute: vi.fn().mockImplementation((sites: unknown[]) => sites),
    };

    mockFindRootScopeQuery = {
      execute: vi.fn().mockResolvedValue(null),
    };

    mockUniqueScopesService = {
      getScopeById: vi.fn().mockResolvedValue(null),
      deleteScope: vi.fn().mockResolvedValue(undefined),
    };

    mockUniqueFilesService = {
      deleteFilesBySiteId: vi.fn().mockResolvedValue(0),
    };

    const mockHistogram = {
      record: vi.fn(),
    };

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(SitesConfigurationService)
      .impl(() => mockSitesConfigurationService)
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => mockPermissionsSyncService)
      .mock(ScopeManagementService)
      .impl(() => mockScopeManagementService)
      .mock(SubsiteDiscoveryService)
      .impl(() => mockSubsiteDiscoveryService)
      .mock(InitializeRootScopeCommand)
      .impl(() => mockInitializeRootScopeCommand)
      .mock(FindRootScopeQuery)
      .impl(() => mockFindRootScopeQuery)
      .mock(DeduplicateSitesQuery)
      .impl(() => mockDeduplicateSitesQuery)
      .mock(UniqueScopesService)
      .impl(() => mockUniqueScopesService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .mock(SPC_SYNC_DURATION_SECONDS)
      .impl(() => mockHistogram)
      .compile();

    service = unit;
  });

  it('synchronizes files from all configured sites', async () => {
    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      expect.any(Object),
      'TestColumn',
    );
    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [mockFile],
      null,
      expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
          scopeId: { type: 'fixed', scopeId: 'scope_test' },
        }),
        siteName: expect.any(Smeared),
        rootPath: expect.any(Smeared),
        serviceUserId: 'user-123',
      }),
    );

    const context = vi.mocked(mockContentSyncService.syncContentForSite).mock.calls[0]?.[2];
    expect(context?.siteName.value).toBe('test-site-name');
    expect(context?.rootPath.value).toBe('/test-root');
  });

  it('delegates content synchronization to ContentSyncService', async () => {
    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [mockFile],
      null,
      expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
          scopeId: { type: 'fixed', scopeId: 'scope_test' },
        }),
        siteName: expect.any(Smeared),
        rootPath: expect.any(Smeared),
        serviceUserId: 'user-123',
      }),
    );

    const context = vi.mocked(mockContentSyncService.syncContentForSite).mock.calls[0]?.[2];
    expect(context?.siteName.value).toBe('test-site-name');
    expect(context?.rootPath.value).toBe('/test-root');
  });

  it('skips site when no items found', async () => {
    mockGraphApiService.getAllSiteItems = vi.fn().mockResolvedValue({ items: [], directories: [] });

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).not.toHaveBeenCalled();
  });

  it('prevents overlapping scans', async () => {
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockImplementation(
        () =>
          new Promise((resolve) =>
            setTimeout(() => resolve({ items: [mockFile], directories: [] }), 100),
          ),
      );

    const firstScan = service.synchronize();
    const secondScan = service.synchronize();

    const [firstResult, secondResult] = await Promise.all([firstScan, secondScan]);

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
    expect(firstResult.fullResult.status).toBe('success');
    expect(secondResult.fullResult.status).toBe('skipped');
    if (secondResult.fullResult.status === 'skipped') {
      expect(secondResult.fullResult.reason).toBe('scan_in_progress');
    }
  });

  it('releases scan lock after completion', async () => {
    await service.synchronize();
    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
  });

  it('releases scan lock after site-level failure', async () => {
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockRejectedValueOnce(new Error('API failure'))
      .mockResolvedValue({ items: [mockFile], directories: [] });

    await service.synchronize();
    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
  });

  it('continues content sync on error and attempts permissions sync', async () => {
    mockContentSyncService.syncContentForSite.mockRejectedValue(new Error('Content sync failed'));

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalled();
    expect(mockPermissionsSyncService.syncPermissionsForSite).not.toHaveBeenCalled();
  });

  it('syncs permissions when enabled', async () => {
    const mockHistogram = {
      record: vi.fn(),
    };

    const mockSiteConfigs = [
      createMockSiteConfig({
        siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
        syncMode: 'content_and_permissions',
      }),
    ];

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(GraphApiService)
      .impl(() => ({
        ...mockGraphApiService,
      }))
      .mock(SitesConfigurationService)
      .impl(() => ({
        ...mockSitesConfigurationService,
        loadSitesConfiguration: vi.fn().mockResolvedValue(mockSiteConfigs),
      }))
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => mockPermissionsSyncService)
      .mock(ScopeManagementService)
      .impl(() => mockScopeManagementService)
      .mock(SubsiteDiscoveryService)
      .impl(() => mockSubsiteDiscoveryService)
      .mock(InitializeRootScopeCommand)
      .impl(() => mockInitializeRootScopeCommand)
      .mock(FindRootScopeQuery)
      .impl(() => mockFindRootScopeQuery)
      .mock(DeduplicateSitesQuery)
      .impl(() => mockDeduplicateSitesQuery)
      .mock(UniqueScopesService)
      .impl(() => mockUniqueScopesService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .mock(SPC_SYNC_DURATION_SECONDS)
      .impl(() => mockHistogram)
      .compile();

    await unit.synchronize();

    expect(mockPermissionsSyncService.syncPermissionsForSite).toHaveBeenCalledWith({
      context: expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
          scopeId: { type: 'fixed', scopeId: 'scope_test' },
        }),
        siteName: expect.any(Smeared),
        rootPath: expect.any(Smeared),
        serviceUserId: 'user-123',
      }),
      sharePoint: { items: [mockFile], directories: [] },
      unique: { folders: null },
    });

    const permissionsCall = vi.mocked(mockPermissionsSyncService.syncPermissionsForSite).mock
      .calls[0]?.[0];
    expect(permissionsCall?.context.siteName.value).toBe('test-site-name');
    expect(permissionsCall?.context.rootPath.value).toBe('/test-root');
  });

  it('skips permissions sync when disabled', async () => {
    await service.synchronize();

    expect(mockPermissionsSyncService.syncPermissionsForSite).not.toHaveBeenCalled();
  });

  it('calls stale scope cleanup after content sync', async () => {
    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledTimes(1);
    expect(mockScopeManagementService.deleteStaleScopes).toHaveBeenCalledTimes(1);
    expect(mockScopeManagementService.deleteStaleScopes).toHaveBeenCalledWith(
      expect.objectContaining({
        value: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
    );
  });

  it('continues global synchronization when stale scope cleanup fails for a site', async () => {
    mockScopeManagementService.deleteStaleScopes.mockRejectedValueOnce(new Error('Cleanup failed'));

    const result = await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledTimes(1);
    expect(mockScopeManagementService.deleteStaleScopes).toHaveBeenCalledTimes(1);
    expect(result.fullResult.status).toBe('success');
  });

  it('handles permissions sync errors gracefully', async () => {
    const mockHistogram = {
      record: vi.fn(),
    };

    const mockSiteConfigs = [
      createMockSiteConfig({ siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false) }),
    ];

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(GraphApiService)
      .impl(() => ({
        ...mockGraphApiService,
      }))
      .mock(SitesConfigurationService)
      .impl(() => ({
        ...mockSitesConfigurationService,
        loadSitesConfiguration: vi.fn().mockResolvedValue(mockSiteConfigs),
      }))
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => ({
        syncPermissionsForSite: vi.fn().mockRejectedValue(new Error('Permissions sync failed')),
      }))
      .mock(ScopeManagementService)
      .impl(() => mockScopeManagementService)
      .mock(SubsiteDiscoveryService)
      .impl(() => mockSubsiteDiscoveryService)
      .mock(InitializeRootScopeCommand)
      .impl(() => mockInitializeRootScopeCommand)
      .mock(FindRootScopeQuery)
      .impl(() => mockFindRootScopeQuery)
      .mock(DeduplicateSitesQuery)
      .impl(() => mockDeduplicateSitesQuery)
      .mock(UniqueScopesService)
      .impl(() => mockUniqueScopesService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .mock(SPC_SYNC_DURATION_SECONDS)
      .impl(() => mockHistogram)
      .compile();

    await unit.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalled();
  });

  it('transforms files to diff items correctly', async () => {
    const fileWithAllFields: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag2',
        id: '01JWNC3IPYIDGEOH52ABAZMI7436JQOOJI',
        name: '2019-BMW-Maintenance.pdf',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/2019-BMW-Maintenance.pdf',
        size: 1027813,
        createdDateTime: '2025-10-02T00:00:00Z',
        lastModifiedDateTime: '2025-10-10T13:59:11Z',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
          driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash2' } },
        listItem: {
          '@odata.etag': 'etag2',
          id: 'item2',
          eTag: 'etag2',
          createdDateTime: '2025-10-10T13:59:11Z',
          lastModifiedDateTime: '2025-10-10T13:59:11Z',
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/2019-BMW-Maintenance.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag2',
            FinanceGPTKnowledge: false,
            FileLeafRef: '2019-BMW-Maintenance.pdf',
            Modified: '2025-10-10T13:59:11Z',
            Created: '2025-10-02T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '1027813',
          },
        },
      },
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: '2019-BMW-Maintenance.pdf',
    };

    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValue({ items: [fileWithAllFields], directories: [] });

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [fileWithAllFields],
      null,
      expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
        }),
      }),
    );
  });

  it('handles missing lastModifiedDateTime gracefully', async () => {
    const fileWithoutTimestamp: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag3',
        id: '01JWNC3IOG5BABTPS62RAZ7T2L6R36MOBV',
        name: '6034030.pdf',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/6034030.pdf',
        size: 932986,
        createdDateTime: '2025-10-02T00:00:00Z',
        lastModifiedDateTime: '2025-10-10T13:59:12Z',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
          driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash3' } },
        listItem: {
          '@odata.etag': 'etag3',
          id: 'item3',
          eTag: 'etag3',
          createdDateTime: '2025-10-10T13:59:12Z',
          lastModifiedDateTime: '2025-10-10T13:59:12Z',
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/6034030.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag3',
            FinanceGPTKnowledge: false,
            FileLeafRef: '6034030.pdf',
            Modified: '2025-10-10T13:59:12Z',
            Created: '2025-10-02T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '932986',
          },
        },
      },
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: '6034030.pdf',
    };

    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValue({ items: [fileWithoutTimestamp], directories: [] });

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [fileWithoutTimestamp],
      null,
      expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
        }),
      }),
    );
  });

  it('processes multiple files from same site', async () => {
    const file1: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: '01JWNC3IKFO6XBRCRFWRHKJ77NAYYM3NTX',
        name: '1173246.pdf',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/1173246.pdf',
        size: 2178118,
        createdDateTime: '2025-10-02T00:00:00Z',
        lastModifiedDateTime: '2025-10-10T13:59:12Z',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
          driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item1',
          eTag: 'etag1',
          createdDateTime: '2025-10-10T13:59:12Z',
          lastModifiedDateTime: '2025-10-10T13:59:12Z',
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/1173246.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: false,
            FileLeafRef: '1173246.pdf',
            Modified: '2025-10-10T13:59:12Z',
            Created: '2025-10-02T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '2178118',
          },
        },
      },
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: '1173246.pdf',
    };

    const file2: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag2',
        id: '01JWNC3IPYIDGEOH52ABAZMI7436JQOOJI',
        name: '2019-BMW-Maintenance.pdf',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/2019-BMW-Maintenance.pdf',
        size: 1027813,
        createdDateTime: '2025-10-02T00:00:00Z',
        lastModifiedDateTime: '2025-10-10T13:59:11Z',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
          driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash2' } },
        listItem: {
          '@odata.etag': 'etag2',
          id: 'item2',
          eTag: 'etag2',
          createdDateTime: '2025-10-10T13:59:11Z',
          lastModifiedDateTime: '2025-10-10T13:59:11Z',
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/2019-BMW-Maintenance.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag2',
            FinanceGPTKnowledge: false,
            FileLeafRef: '2019-BMW-Maintenance.pdf',
            Modified: '2025-10-10T13:59:11Z',
            Created: '2025-10-02T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '1027813',
          },
        },
      },
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: '2019-BMW-Maintenance.pdf',
    };

    const file3: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag3',
        id: '01JWNC3IOG5BABTPS62RAZ7T2L6R36MOBV',
        name: '6034030.pdf',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/6034030.pdf',
        size: 932986,
        createdDateTime: '2025-10-02T00:00:00Z',
        lastModifiedDateTime: '2025-10-10T13:59:10Z',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        parentReference: {
          driveType: 'documentLibrary',
          siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
          driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          id: 'parent1',
          name: 'Documents',
          path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash3' } },
        listItem: {
          '@odata.etag': 'etag3',
          id: 'item3',
          eTag: 'etag3',
          createdDateTime: '2025-10-10T13:59:10Z',
          lastModifiedDateTime: '2025-10-10T13:59:10Z',
          webUrl:
            'https://uniqueapp.sharepoint.com/sites/UniqueAG/Freigegebene%20Dokumente/test-sharepoint-connector-v2/6034030.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag3',
            FinanceGPTKnowledge: false,
            FileLeafRef: '6034030.pdf',
            Modified: '2025-10-10T13:59:10Z',
            Created: '2025-10-02T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1',
            EditorLookupId: '1',
            ItemChildCount: '0',
            FolderChildCount: '0',
            _ModerationStatus: ModerationStatus.Approved,
            FileSizeDisplay: '932986',
          },
        },
      },
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: '6034030.pdf',
    };

    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValue({ items: [file1, file2, file3], directories: [] });

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [file1, file2, file3],
      null,
      expect.objectContaining({
        siteConfig: expect.objectContaining({
          siteId: expect.any(Smeared),
        }),
      }),
    );
  });

  it('does not discover subsites when subsitesScan is disabled', async () => {
    await service.synchronize();

    expect(mockSubsiteDiscoveryService.discoverAllSubsites).not.toHaveBeenCalled();
  });

  it('includes subsite items when subsitesScan is enabled', async () => {
    const siteConfig = createMockSiteConfig({
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      subsitesScan: 'enabled',
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([siteConfig]);

    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('subsite-1', false),
        name: new Smeared('SubA', false),
        relativePath: new Smeared('SubA', false),
      },
    ]);

    const subsiteFile: SharepointContentItem = {
      ...mockFile,
      siteId: new Smeared('subsite-1', false),
    };
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [mockFile], directories: [] })
      .mockResolvedValueOnce({ items: [subsiteFile], directories: [] });

    await service.synchronize();

    expect(mockSubsiteDiscoveryService.discoverAllSubsites).toHaveBeenCalledWith(
      siteConfig.siteId,
      new Smeared('test-site-name', false),
      expect.any(Set),
    );
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
    const getAllSiteItemsMock = mockGraphApiService.getAllSiteItems as ReturnType<typeof vi.fn>;
    expect(
      mockSubsiteDiscoveryService.discoverAllSubsites.mock.invocationCallOrder[0],
    ).toBeLessThan(getAllSiteItemsMock.mock.invocationCallOrder[0] ?? Number.MAX_SAFE_INTEGER);
    expect(getAllSiteItemsMock).toHaveBeenNthCalledWith(1, siteConfig.siteId, expect.any(String));
    expect(getAllSiteItemsMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ value: 'subsite-1' }),
      expect.any(String),
    );
    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [mockFile, { ...subsiteFile, syncSiteId: siteConfig.siteId }],
      null,
      expect.anything(),
    );
  });

  it('fails site sync when subsite discovery fails', async () => {
    const siteConfig = createMockSiteConfig({
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      subsitesScan: 'enabled',
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([siteConfig]);

    mockSubsiteDiscoveryService.discoverAllSubsites.mockRejectedValue(
      new Error('Discovery failed'),
    );

    const result = await service.synchronize();

    expect(result.fullResult.status).toBe('success');
    expect(mockContentSyncService.syncContentForSite).not.toHaveBeenCalled();
  });

  it('fails site sync when subsite item fetch fails', async () => {
    const siteConfig = createMockSiteConfig({
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      subsitesScan: 'enabled',
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([siteConfig]);

    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('subsite-1', false),
        name: new Smeared('SubA', false),
        relativePath: new Smeared('SubA', false),
      },
    ]);

    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [mockFile], directories: [] })
      .mockRejectedValueOnce(new Error('Subsite fetch failed'));

    const result = await service.synchronize();

    expect(result.fullResult.status).toBe('success');
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
    expect(mockContentSyncService.syncContentForSite).not.toHaveBeenCalled();
  });

  it('skips discovered subsites that are already configured as standalone sites', async () => {
    const parentSiteConfig = createMockSiteConfig({
      siteId: new Smeared('parent-site-id', false),
      scopeId: { type: 'fixed', scopeId: 'scope_parent' },
      subsitesScan: 'enabled',
    });
    const standaloneSiteConfig = createMockSiteConfig({
      siteId: new Smeared('host,col,subsite-web-id', false),
      scopeId: { type: 'fixed', scopeId: 'scope_standalone' },
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi
      .fn()
      .mockResolvedValue([parentSiteConfig, standaloneSiteConfig]);

    // discoverAllSubsites receives configuredSubsiteIds and filters internally,
    // so the mock returns only non-excluded subsites
    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('host,col,other-subsite', false),
        name: new Smeared('SubB', false),
        relativePath: new Smeared('SubB', false),
      },
    ]);

    const parentFile: SharepointContentItem = { ...mockFile, siteId: parentSiteConfig.siteId };
    const otherSubsiteFile: SharepointContentItem = {
      ...mockFile,
      siteId: new Smeared('host,col,other-subsite', false),
    };
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [parentFile], directories: [] })
      .mockResolvedValueOnce({ items: [otherSubsiteFile], directories: [] })
      .mockResolvedValue({ items: [mockFile], directories: [] });

    await service.synchronize();

    expect(mockSubsiteDiscoveryService.discoverAllSubsites).toHaveBeenCalledWith(
      parentSiteConfig.siteId,
      expect.any(Smeared),
      new Set(['host,col,subsite-web-id']),
    );
    // 3 calls: parent site, non-configured subsite (SubB) via discovery, standalone site via its
    // own sync. Without the guard, there would be 4 calls (SubA also fetched via discovery)
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(3);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      parentSiteConfig.siteId,
      expect.any(String),
    );
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      expect.objectContaining({ value: 'host,col,other-subsite' }),
      expect.any(String),
    );
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      standaloneSiteConfig.siteId,
      expect.any(String),
    );
  });

  it('skips discovered subsites that are configured as inactive or deleted standalone sites', async () => {
    const parentSiteConfig = createMockSiteConfig({
      siteId: new Smeared('parent-site-id', false),
      scopeId: { type: 'fixed', scopeId: 'scope_parent' },
      subsitesScan: 'enabled',
    });
    const inactiveSubsiteConfig = createMockSiteConfig({
      siteId: new Smeared('host,col,inactive-subsite', false),
      scopeId: { type: 'fixed', scopeId: 'scope_inactivesub' },
      syncStatus: 'inactive',
    });
    const deletedSubsiteConfig = createMockSiteConfig({
      siteId: new Smeared('host,col,deleted-subsite', false),
      scopeId: { type: 'fixed', scopeId: 'scope_deletedsub' },
      syncStatus: 'deleted',
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi
      .fn()
      .mockResolvedValue([parentSiteConfig, inactiveSubsiteConfig, deletedSubsiteConfig]);

    // discoverAllSubsites receives configuredSubsiteIds (including inactive/deleted) and filters
    // internally
    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('host,col,other-subsite', false),
        name: new Smeared('OtherSubsite', false),
        relativePath: new Smeared('OtherSubsite', false),
      },
    ]);

    const otherSubsiteFile: SharepointContentItem = {
      ...mockFile,
      siteId: new Smeared('host,col,other-subsite', false),
    };

    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [mockFile], directories: [] })
      .mockResolvedValueOnce({ items: [otherSubsiteFile], directories: [] });

    await service.synchronize();

    expect(mockSubsiteDiscoveryService.discoverAllSubsites).toHaveBeenCalledWith(
      parentSiteConfig.siteId,
      expect.any(Smeared),
      new Set(['host,col,inactive-subsite', 'host,col,deleted-subsite']),
    );
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      parentSiteConfig.siteId,
      expect.any(String),
    );
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      expect.objectContaining({ value: 'host,col,other-subsite' }),
      expect.any(String),
    );
  });

  // This test case is here for purely documentation purposes. This should never happen that subsite
  // is configured with simple UUID, because to fetch them via API we need to use the compound ID.
  it('does not skip subsites when configured sites use plain UUID format', async () => {
    const parentSiteConfig = createMockSiteConfig({
      siteId: new Smeared('parent-site-id', false),
      scopeId: { type: 'fixed', scopeId: 'scope_parent' },
      subsitesScan: 'enabled',
    });
    const uuidSiteConfig = createMockSiteConfig({
      siteId: new Smeared('some-uuid-site-id', false),
      scopeId: { type: 'fixed', scopeId: 'scope_uuid' },
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi
      .fn()
      .mockResolvedValue([parentSiteConfig, uuidSiteConfig]);

    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('host,col,discovered-subsite', false),
        name: new Smeared('SubA', false),
        relativePath: new Smeared('SubA', false),
      },
    ]);

    const subsiteFile: SharepointContentItem = {
      ...mockFile,
      siteId: new Smeared('host,col,discovered-subsite', false),
    };
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [mockFile], directories: [] })
      .mockResolvedValueOnce({ items: [subsiteFile], directories: [] })
      .mockResolvedValue({ items: [mockFile], directories: [] });

    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      expect.objectContaining({ value: 'host,col,discovered-subsite' }),
      expect.any(String),
    );
  });

  it('cleans up stale scopes using parent site ID when subsites are enabled', async () => {
    const siteConfig = createMockSiteConfig({
      siteId: new Smeared('bd9c85ee-998f-4665-9c44-577cf5a08a66', false),
      subsitesScan: 'enabled',
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([siteConfig]);

    mockSubsiteDiscoveryService.discoverAllSubsites.mockResolvedValue([
      {
        siteId: new Smeared('subsite-b', false),
        name: new Smeared('B', false),
        relativePath: new Smeared('B', false),
      },
    ]);

    const subsiteFile: SharepointContentItem = {
      ...mockFile,
      siteId: new Smeared('subsite-b', false),
    };
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockResolvedValueOnce({ items: [mockFile], directories: [] })
      .mockResolvedValueOnce({ items: [subsiteFile], directories: [] });

    await service.synchronize();

    expect(mockScopeManagementService.deleteStaleScopes).toHaveBeenCalledTimes(1);
    expect(mockScopeManagementService.deleteStaleScopes).toHaveBeenCalledWith(siteConfig.siteId);
  });

  it('does not initialize root scope when getSiteInfo fails', async () => {
    mockGraphApiService.getSiteInfo = vi.fn().mockRejectedValue(new Error('Site not found'));

    const result = await service.synchronize();

    expect(result.fullResult.status).toBe('success');
    expect(mockGraphApiService.getSiteInfo).toHaveBeenCalled();
    expect(mockInitializeRootScopeCommand.execute).not.toHaveBeenCalled();
    expect(mockContentSyncService.syncContentForSite).not.toHaveBeenCalled();
  });

  it('calls getSiteInfo before initializeRootScopeCommand', async () => {
    const callOrder: string[] = [];
    mockGraphApiService.getSiteInfo = vi.fn().mockImplementation(async () => {
      callOrder.push('getSiteInfo');
      return { siteName: new Smeared('test-site-name', false), managedPath: 'sites' };
    });
    mockInitializeRootScopeCommand.execute = vi.fn().mockImplementation(async () => {
      callOrder.push('initializeRootScope');
      return {
        rootScopeId: 'scope_test',
        serviceUserId: 'user-123',
        rootPath: new Smeared('/test-root', false),
        isInitialSync: false,
      };
    });

    await service.synchronize();

    expect(callOrder).toEqual(['getSiteInfo', 'initializeRootScope']);
  });

  it('delegates site list deduplication to DeduplicateSitesQuery', async () => {
    const site1 = createMockSiteConfig({
      siteId: new Smeared('site-1', false),
      scopeId: { type: 'fixed', scopeId: 'scope_a' },
    });
    const site2 = createMockSiteConfig({
      siteId: new Smeared('site-2', false),
      scopeId: { type: 'fixed', scopeId: 'scope_b' },
    });
    mockSitesConfigurationService.loadSitesConfiguration = vi
      .fn()
      .mockResolvedValue([site1, site2]);
    mockDeduplicateSitesQuery.execute = vi.fn().mockReturnValue([site1]);

    await service.synchronize();

    expect(mockDeduplicateSitesQuery.execute).toHaveBeenCalledWith([site1, site2]);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      expect.objectContaining({ value: site1.siteId.value }),
      expect.any(String),
    );
  });

  it('maps RootScopeResolutionError from the command to RootScopeResolution failure step', async () => {
    mockInitializeRootScopeCommand.execute = vi.fn().mockRejectedValue(
      new RootScopeResolutionError('claim_failed', {
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
        parentScopeId: 'scope_parent',
        siteName: createSmeared('test-site-name'),
        detail: 'claim failed',
      }),
    );

    const result = await service.synchronize();

    const siteResult = result.siteResults[0]?.result;
    expect(siteResult).toEqual({
      status: 'failure',
      step: SiteSyncStep.RootScopeResolution,
    });
  });

  it('maps generic errors from the command to RootScopeInit failure step', async () => {
    mockInitializeRootScopeCommand.execute = vi
      .fn()
      .mockRejectedValue(new Error('something else broke'));

    const result = await service.synchronize();

    const siteResult = result.siteResults[0]?.result;
    expect(siteResult).toEqual({
      status: 'failure',
      step: SiteSyncStep.RootScopeInit,
    });
  });

  describe('processSiteDeletions', () => {
    const FIXED_SCOPE_ID = 'scope_fixed_target';
    const AUTO_PARENT_SCOPE_ID = 'scope_parent';

    const fixedDeletedSite = (): ReturnType<typeof createMockSiteConfig> =>
      createMockSiteConfig({
        siteId: new Smeared('site-deleted-fixed', false),
        scopeId: { type: 'fixed', scopeId: FIXED_SCOPE_ID },
        syncStatus: 'deleted',
      });

    const autoDeletedSite = (): ReturnType<typeof createMockSiteConfig> =>
      createMockSiteConfig({
        siteId: new Smeared('site-deleted-auto', false),
        scopeId: { type: 'auto', parentScopeId: AUTO_PARENT_SCOPE_ID },
        syncStatus: 'deleted',
      });

    const claimedScope = (id: string) => ({
      id,
      name: 'claimed',
      parentId: AUTO_PARENT_SCOPE_ID,
      externalId: 'site::site-deleted-auto',
    });

    it('skips deletion side effects for fixed rows when scope is not found', async () => {
      mockSitesConfigurationService.loadSitesConfiguration = vi
        .fn()
        .mockResolvedValue([fixedDeletedSite()]);
      mockUniqueScopesService.getScopeById = vi.fn().mockResolvedValue(null);

      await service.synchronize();

      expect(mockFindRootScopeQuery.execute).not.toHaveBeenCalled();
      expect(mockUniqueScopesService.getScopeById).toHaveBeenCalledWith(FIXED_SCOPE_ID);
      expect(mockUniqueFilesService.deleteFilesBySiteId).not.toHaveBeenCalled();
      expect(mockScopeManagementService.resetRootScope).not.toHaveBeenCalled();
      expect(mockUniqueScopesService.deleteScope).not.toHaveBeenCalled();
    });

    it('resets the root scope for fixed rows when scope is found, deleting files first', async () => {
      const site = fixedDeletedSite();
      mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([site]);
      mockUniqueScopesService.getScopeById = vi.fn().mockResolvedValue({
        id: FIXED_SCOPE_ID,
        name: 'fixed-scope',
        parentId: null,
        externalId: null,
      });

      await service.synchronize();

      expect(mockFindRootScopeQuery.execute).not.toHaveBeenCalled();
      expect(mockUniqueScopesService.getScopeById).toHaveBeenCalledWith(FIXED_SCOPE_ID);
      expect(mockUniqueFilesService.deleteFilesBySiteId).toHaveBeenCalledWith(site.siteId);
      expect(mockScopeManagementService.resetRootScope).toHaveBeenCalledWith(FIXED_SCOPE_ID);
      expect(mockUniqueScopesService.deleteScope).not.toHaveBeenCalled();

      const deleteFilesOrder =
        mockUniqueFilesService.deleteFilesBySiteId.mock.invocationCallOrder[0] ??
        Number.MAX_SAFE_INTEGER;
      const resetOrder = mockScopeManagementService.resetRootScope.mock.invocationCallOrder[0] ?? 0;
      expect(deleteFilesOrder).toBeLessThan(resetOrder);
    });

    it('skips deletion side effects for auto rows when scope is not found', async () => {
      const site = autoDeletedSite();
      mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([site]);
      mockFindRootScopeQuery.execute = vi.fn().mockResolvedValue(null);

      await service.synchronize();

      expect(mockFindRootScopeQuery.execute).toHaveBeenCalledTimes(1);
      expect(mockFindRootScopeQuery.execute).toHaveBeenCalledWith(site);
      expect(mockUniqueFilesService.deleteFilesBySiteId).not.toHaveBeenCalled();
      expect(mockScopeManagementService.resetRootScope).not.toHaveBeenCalled();
      expect(mockUniqueScopesService.deleteScope).not.toHaveBeenCalled();
    });

    it('deletes the auto-created root scope after resetting it', async () => {
      const site = autoDeletedSite();
      const found = claimedScope('scope_auto_root');
      mockSitesConfigurationService.loadSitesConfiguration = vi.fn().mockResolvedValue([site]);
      mockFindRootScopeQuery.execute = vi.fn().mockResolvedValueOnce(found);

      await service.synchronize();

      expect(mockFindRootScopeQuery.execute).toHaveBeenCalledWith(site);
      expect(mockUniqueFilesService.deleteFilesBySiteId).toHaveBeenCalledWith(site.siteId);
      expect(mockScopeManagementService.resetRootScope).toHaveBeenCalledWith(found.id);
      expect(mockUniqueScopesService.deleteScope).toHaveBeenCalledWith(found.id, {
        recursive: true,
      });

      const resetOrder =
        mockScopeManagementService.resetRootScope.mock.invocationCallOrder[0] ??
        Number.MAX_SAFE_INTEGER;
      const deleteOrder = mockUniqueScopesService.deleteScope.mock.invocationCallOrder[0] ?? 0;
      expect(resetOrder).toBeLessThan(deleteOrder);
    });

    it('continues with other sites when a deletion step fails', async () => {
      const failingSite = createMockSiteConfig({
        siteId: new Smeared('site-deleted-fails', false),
        scopeId: { type: 'fixed', scopeId: 'scope_fails' },
        syncStatus: 'deleted',
      });
      const survivingSite = createMockSiteConfig({
        siteId: new Smeared('site-deleted-ok', false),
        scopeId: { type: 'fixed', scopeId: 'scope_ok' },
        syncStatus: 'deleted',
      });
      mockSitesConfigurationService.loadSitesConfiguration = vi
        .fn()
        .mockResolvedValue([failingSite, survivingSite]);
      mockUniqueScopesService.getScopeById = vi.fn().mockResolvedValue({
        id: 'whatever',
        name: 'n',
        parentId: null,
        externalId: null,
      });
      mockScopeManagementService.resetRootScope = vi
        .fn()
        .mockRejectedValueOnce(new Error('reset blew up'))
        .mockResolvedValue(undefined);

      await service.synchronize();

      expect(mockScopeManagementService.resetRootScope).toHaveBeenCalledTimes(2);
      expect(mockUniqueFilesService.deleteFilesBySiteId).toHaveBeenCalledTimes(2);
    });
  });
});
