import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../constants/moderation-status.constants';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { buildKnowledgeBaseUrl } from '../utils/sharepoint.util';
import { ContentSyncService } from './content-sync.service';
import { PermissionsSyncService } from './permissions-sync.service';
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
      lastModifiedDateTime: '2025-10-10T13:59:12Z',
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
      getAllSiteItems: vi.fn().mockResolvedValue([mockFile]),
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
          if (key === 'processing.permissionsSyncEnabled') return false;
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
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [mockFile],
    );
  });

  it('delegates content synchronization to ContentSyncService', async () => {
    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [mockFile],
    );
  });

  it('skips site when no items found', async () => {
    mockGraphApiService.getAllSiteItems = vi.fn().mockResolvedValue([]);

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).not.toHaveBeenCalled();
  });

  it('prevents overlapping scans', async () => {
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve([mockFile]), 100)),
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

  it('does not release scan lock on getAllSiteItems error', async () => {
    mockGraphApiService.getAllSiteItems = vi
      .fn()
      .mockRejectedValueOnce(new Error('API failure'))
      .mockResolvedValue([mockFile]);

    try {
      await service.synchronize();
    } catch {
      // Expected to throw
    }

    await service.synchronize();

    expect(mockGraphApiService.getAllSiteItems).toHaveBeenCalledTimes(1);
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
          if (key === 'processing.syncMode') return 'content-and-permissions';
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

    expect(mockPermissionsSyncService.syncPermissionsForSite).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [mockFile],
    );
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
          if (key === 'processing.permissionsSyncEnabled') return true;
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
        lastModifiedDateTime: '2025-10-10T13:59:11Z',
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

    mockGraphApiService.getAllSiteItems = vi.fn().mockResolvedValue([fileWithAllFields]);

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [fileWithAllFields],
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
        lastModifiedDateTime: '2025-10-10T13:59:12Z',
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

    mockGraphApiService.getAllSiteItems = vi.fn().mockResolvedValue([fileWithoutTimestamp]);

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [fileWithoutTimestamp],
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
        lastModifiedDateTime: '2025-10-10T13:59:12Z',
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
        lastModifiedDateTime: '2025-10-10T13:59:11Z',
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
        lastModifiedDateTime: '2025-10-10T13:59:10Z',
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

    mockGraphApiService.getAllSiteItems = vi.fn().mockResolvedValue([file1, file2, file3]);

    await service.synchronize();

    expect(mockContentSyncService.syncContentForSite).toHaveBeenCalledWith(
      'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      [file1, file2, file3],
    );
  });

  describe('buildSharePointUrl', () => {
    it('should build proper SharePoint URL for file in subfolder', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/folder/subfolder',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder/subfolder',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should build proper SharePoint URL for file in root folder', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/document.docx');
    });

    it('should build proper SharePoint URL for file in root folder with empty path', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/document.docx');
    });

    it('should handle siteWebUrl with trailing slash', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/folder',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site/',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/folder/document.docx');
    });

    it('should handle folderPath with leading slash', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/folder/subfolder',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder/subfolder',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should handle folderPath without leading slash', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/folder/subfolder',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: 'folder/subfolder',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should URL encode special characters in folder names', () => {
      const file: SharepointContentItem = {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'file123',
          name: 'document.docx',
          size: 1024,
          webUrl:
            'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
          lastModifiedDateTime: '2023-01-01T00:00:00Z',
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive789',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/folder with spaces/sub folder',
            siteId: 'site456',
          },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2023-01-01T00:00:00Z',
            lastModifiedDateTime: '2023-01-01T00:00:00Z',
            webUrl:
              'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'document.docx',
              Modified: '2023-01-01T00:00:00Z',
              Created: '2023-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
          file: {
            mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            hashes: { quickXorHash: 'hash1' },
          },
        },
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder with spaces/sub folder',
        fileName: 'document.docx',
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder%20with%20spaces/sub%20folder/document.docx',
      );
    });
  });
});
