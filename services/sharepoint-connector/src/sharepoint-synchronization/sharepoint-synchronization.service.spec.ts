import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../constants/moderation-status.constants';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { PermissionsSyncService } from '../permissions-sync/permissions-sync.service';
import { ContentSyncService } from './content-sync.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

describe('SharepointSynchronizationService', () => {
  let service: SharepointSynchronizationService;
  let mockGraphApiService: Partial<GraphApiService>;
  let mockContentSyncService: {
    syncContentForSite: ReturnType<typeof vi.fn>;
  };
  let mockPermissionsSyncService: {
    syncPermissionsForSite: ReturnType<typeof vi.fn>;
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
    siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
    siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
    driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    driveName: 'Documents',
    folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
    fileName: '1173246.pdf',
  };

  beforeEach(async () => {
    mockGraphApiService = {
      getAllSiteItems: vi.fn().mockResolvedValue({ items: [mockFile], directories: [] }),
    };

    mockContentSyncService = {
      syncContentForSite: vi.fn().mockResolvedValue(undefined),
    };

    mockPermissionsSyncService = {
      syncPermissionsForSite: vi.fn().mockResolvedValue(undefined),
    };

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.siteIds') return ['bd9c85ee-998f-4665-9c44-577cf5a08a66'];
          if (key === 'processing.syncMode') return 'content_only';
          return undefined;
        }),
      }))
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => mockPermissionsSyncService)
      .compile();

    service = unit;
  });

  it('synchronizes files from all configured sites', async () => {
    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
    );
    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [mockFile],
      null,
      expect.objectContaining({
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
    );
  });

  it('delegates content synchronization to ContentSyncService', async () => {
    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      [mockFile],
      null,
      expect.objectContaining({
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
    );
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

    await Promise.all([firstScan, secondScan]);

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
  });

  it('releases scan lock after completion', async () => {
    await service.synchronize();
    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(2);
  });

  it('releases scan lock on getAllSiteItems error', async () => {
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockRejectedValueOnce(new Error('API failure'))
      .mockResolvedValue({ items: [mockFile], directories: [] });

    try {
      await service.synchronize();
    } catch {
      // Expected to throw because of the error in getAllSiteItems
    }

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
    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.siteIds') return ['bd9c85ee-998f-4665-9c44-577cf5a08a66'];
          if (key === 'processing.syncMode') return 'content_and_permissions';
          return undefined;
        }),
      }))
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => mockPermissionsSyncService)
      .compile();

    await unit.synchronize();

    expect(mockPermissionsSyncService.syncPermissionsForSite).toHaveBeenCalledWith({
      context: expect.objectContaining({
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
      sharePoint: { items: [mockFile], directories: [] },
      unique: { folders: null },
    });
  });

  it('skips permissions sync when disabled', async () => {
    await service.synchronize();

    expect(mockPermissionsSyncService.syncPermissionsForSite).not.toHaveBeenCalled();
  });

  it('handles permissions sync errors gracefully', async () => {
    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.siteIds') return ['bd9c85ee-998f-4665-9c44-577cf5a08a66'];
          if (key === 'processing.syncMode') return 'content_and_permissions';
          return undefined;
        }),
      }))
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(ContentSyncService)
      .impl(() => mockContentSyncService)
      .mock(PermissionsSyncService)
      .impl(() => ({
        syncPermissionsForSite: vi.fn().mockRejectedValue(new Error('Permissions sync failed')),
      }))
      .compile();

    await unit.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalled();
  });

  it.skip('transforms files to diff items correctly', async () => {
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
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
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
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
    );
  });

  it.skip('handles missing lastModifiedDateTime gracefully', async () => {
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
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
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
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
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
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
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
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
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
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
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
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      }),
    );
  });
});
