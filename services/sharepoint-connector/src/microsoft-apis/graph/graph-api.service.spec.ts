import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphClientFactory } from './graph-client.factory';
import type { DriveItem, ListColumn, ListItem } from './types/sharepoint.types';
import type { SharepointContentItem } from './types/sharepoint-content-item.interface';

describe('GraphApiService', () => {
  let service: GraphApiService;
  let mockGraphClient: {
    api: ReturnType<typeof vi.fn>;
  };
  let mockFileFilterService: Partial<FileFilterService>;
  let maxFilesToScanConfig: number | undefined;

  const mockDrive = { id: 'drive-1', name: 'Documents' };

  beforeEach(async () => {
    mockGraphClient = {
      api: vi.fn(),
    };
    maxFilesToScanConfig = undefined;

    const mockChain = {
      get: vi.fn(),
      select: vi.fn(),
      expand: vi.fn(),
      top: vi.fn(),
      getStream: vi.fn(),
    };

    mockChain.select.mockReturnValue(mockChain);
    mockChain.expand.mockReturnValue(mockChain);
    mockChain.top.mockReturnValue(mockChain);
    mockGraphClient.api.mockReturnValue(mockChain);

    // Mock get() calls based on the API endpoint
    mockChain.get.mockImplementation((path?: string) => {
      if (path?.includes('/lists')) {
        // Return empty lists for getListsForSite
        return Promise.resolve({ value: [] });
      }
      if (path?.includes('/drives/')) {
        // Return mock drive for getDrivesForSite
        return Promise.resolve({ value: [mockDrive] });
      }
      if (path?.includes('/sites/') && path?.includes('/webUrl')) {
        // Return site web URL
        return Promise.resolve({ webUrl: 'https://contoso.sharepoint.com/sites/test' });
      }
      // Default: return empty result to terminate pagination
      return Promise.resolve({ value: [] });
    });

    mockFileFilterService = {
      isFileValidForIngestion: vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'],
      isListItemValidForIngestion: vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isListItemValidForIngestion'],
    };

    const { unit } = await TestBed.solitary(GraphApiService)
      .mock(GraphClientFactory)
      .impl(() => ({
        createClient: () => mockGraphClient,
      }))
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.graphApiRateLimitPerMinuteThousands') return 10;
          if (key === 'processing.maxFilesToScan') return maxFilesToScanConfig;
          return undefined;
        }),
      }))
      .mock(FileFilterService)
      .impl(() => mockFileFilterService)
      .compile();

    service = unit;

    // Mock the rate limiter to avoid async issues
    // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
    (service as any).makeRateLimitedRequest = vi.fn().mockImplementation(
      // biome-ignore lint/suspicious/noExplicitAny: Generic promise type for mocking
      async (requestFn: () => Promise<any>) => {
        return requestFn();
      },
    );
  });

  describe('getListColumns', () => {
    it('successfully fetches list columns', async () => {
      const mockColumns: ListColumn[] = [
        { id: '1', name: 'Title', displayName: 'Title' },
        { id: '2', name: 'Created', displayName: 'Created' },
      ];

      // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
      (service as any).paginateGraphApiRequest = vi.fn().mockResolvedValue(mockColumns);

      const result = await service.getListColumns('site-1', 'list-1');

      expect(result).toEqual(mockColumns);
      // biome-ignore lint/suspicious/noExplicitAny: Check private method call
      expect((service as any).paginateGraphApiRequest).toHaveBeenCalledWith(
        '/sites/site-1/lists/list-1/columns',
        expect.any(Function),
      );
    });

    it('throws error when fetching columns fails', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
      (service as any).paginateGraphApiRequest = vi.fn().mockRejectedValue(new Error('API Error'));

      await expect(service.getListColumns('site-1', 'list-1')).rejects.toThrow('API Error');
    });
  });

  describe('getAllFilesAndPagesForSite', () => {
    const mockSharepointContentItem: SharepointContentItem = {
      itemType: 'driveItem',
      item: {
        '@odata.etag': 'etag1',
        id: 'file-1',
        name: 'test.pdf',
        size: 1024,
        webUrl: 'https://sharepoint.example.com/test.pdf',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
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
          id: 'parent-1',
          name: 'Documents',
          path: '/drive/root:/',
          siteId: 'site-1',
        },
        file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
        listItem: {
          '@odata.etag': 'etag1',
          id: 'item-1',
          eTag: 'etag1',
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-01-01T00:00:00Z',
          webUrl: 'https://sharepoint.example.com/test.pdf',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          fields: {
            '@odata.etag': 'etag1',
            FinanceGPTKnowledge: true,
            FileLeafRef: 'test.pdf',
            Modified: '2024-01-01T00:00:00Z',
            Created: '2024-01-01T00:00:00Z',
            ContentType: 'Document',
            AuthorLookupId: '1704',
            EditorLookupId: '1704',
            FileSizeDisplay: '12345',
            ItemChildCount: '0',
            FolderChildCount: '0',
          },
        },
      },
      siteId: 'site-1',
      driveId: 'drive-1',
      driveName: 'Documents',
      folderPath: '/',
      fileName: 'test.pdf',
    };

    // biome-ignore lint/suspicious/noExplicitAny: Mock data for testing site pages which have different structure
    const mockEnrichedSitePage: any = {
      itemType: 'sitePage' as const,
      id: 'page-1',
      name: 'test.aspx',
      size: 512,
      webUrl: 'https://sharepoint.example.com/test.aspx',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      siteId: 'site-1',
      driveId: 'sitepages-list',
      driveName: 'SitePages',
      folderPath: '/',
      listItem: {
        fields: {
          FileLeafRef: 'test.aspx',
          Title: 'Test Page',
        },
      },
    };

    it('finds syncable files across multiple drives', async () => {
      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [mockSharepointContentItem],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(1);
      expect(result.directories).toHaveLength(0);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
    });

    it('skips drives without IDs', async () => {
      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [mockSharepointContentItem],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(1);
      expect(result.directories).toHaveLength(0);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
    });

    it('handles pagination correctly', async () => {
      // biome-ignore lint/suspicious/noExplicitAny: File variant for pagination test
      const file2: any = {
        ...mockSharepointContentItem,
        id: 'file-2',
        name: 'test2.pdf',
      };

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([mockEnrichedSitePage]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [file2],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(2);
      expect(result.directories).toHaveLength(0);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
    });

    it('filters out non-syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(false) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(0);
      expect(result.directories).toHaveLength(0);
    });

    it('recursively scans folders', async () => {
      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [mockSharepointContentItem],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(1);
      expect(result.directories).toHaveLength(0);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1', 'TestColumn');
    });

    it('counts total files vs syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockImplementation(
          (file) => file.name !== 'invalid.exe',
        ) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue({
        items: [mockSharepointContentItem],
        directories: [],
      });

      const result = await service.getAllSiteItems('site-1', 'TestColumn');

      expect(result.items).toHaveLength(1);
      expect(result.directories).toHaveLength(0);
      expect(result.items[0]).toBeDefined();
      if (result.items[0]) {
        expect(result.items[0].itemType === 'driveItem').toBe(true);
        expect((result.items[0].item as DriveItem).name).toBe('test.pdf');
      }
    });

    it('limits site pages by maxFilesToScan', async () => {
      const firstItem = {
        id: 'item-1',
        fields: {
          FileLeafRef: 'page1.aspx',
          Title: 'Page 1',
        },
        webUrl: '/sites/site-1/sitepages/page1.aspx',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        createdDateTime: '2024-01-01T00:00:00Z',
      };
      const secondItem = {
        id: 'item-2',
        fields: {
          FileLeafRef: 'page2.aspx',
          Title: 'Page 2',
        },
        webUrl: '/sites/site-1/sitepages/page2.aspx',
        lastModifiedDateTime: '2024-01-02T00:00:00Z',
        createdDateTime: '2024-01-02T00:00:00Z',
      };

      vi.spyOn(service, 'getListItems').mockResolvedValue([
        firstItem,
        secondItem,
      ] as unknown as ListItem[]);
      maxFilesToScanConfig = 1;

      const result = await service.getAspxListItems(
        'site-1',
        'list-1',
        'FinanceGPTKnowledge',
        maxFilesToScanConfig,
      );

      expect(result).toHaveLength(1);
      expect(result[0]?.fileName).toBe('Page 1');
      expect(service.getListItems).toHaveBeenCalled();
    });
  });

  describe('getSitePageContent', () => {
    it('retrieves page content with canvas and wiki content', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          CanvasContent1: '<div>Modern content</div>',
          WikiField: '<div>Legacy content</div>',
          Title: 'Test Page',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: '<div>Modern content</div>',
        wikiField: '<div>Legacy content</div>',
        title: 'Test Page',
      });
      expect(mockGraphClient.api).toHaveBeenCalledWith('/sites/site-1/lists/list-1/items/item-1');
      expect(mockChain.expand).toHaveBeenCalledWith(
        'fields($select=CanvasContent1,WikiField,Title)',
      );
    });

    it('handles missing CanvasContent1 field', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          WikiField: '<div>Legacy content</div>',
          Title: 'Test Page',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: undefined,
        wikiField: '<div>Legacy content</div>',
        title: 'Test Page',
      });
    });

    it('handles missing WikiField field', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          CanvasContent1: '<div>Modern content</div>',
          Title: 'Test Page',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: '<div>Modern content</div>',
        wikiField: undefined,
        title: 'Test Page',
      });
    });

    it('handles missing Title field', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          CanvasContent1: '<div>Modern content</div>',
          WikiField: '<div>Legacy content</div>',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: '<div>Modern content</div>',
        wikiField: '<div>Legacy content</div>',
        title: undefined,
      });
    });

    it('throws error when response lacks fields', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({});

      await expect(service.getAspxPageContent('site-1', 'list-1', 'item-1')).rejects.toThrow(
        'MS Graph response missing fields for page content',
      );
    });
  });
});
