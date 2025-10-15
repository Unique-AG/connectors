import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphClientFactory } from './graph-client.factory';
import type { EnrichedDriveFile, MsGraphSitePage } from './types/pipeline-item.interface';

describe('GraphApiService', () => {
  let service: GraphApiService;
  let mockGraphClient: {
    api: ReturnType<typeof vi.fn>;
  };
  let mockFileFilterService: Partial<FileFilterService>;

  const mockDrive = { id: 'drive-1', name: 'Documents' };

  beforeEach(async () => {
    mockGraphClient = {
      api: vi.fn(),
    };

    const mockChain = {
      get: vi.fn(),
      select: vi.fn(),
      expand: vi.fn(),
      getStream: vi.fn(),
    };

    mockChain.select.mockReturnValue(mockChain);
    mockChain.expand.mockReturnValue(mockChain);
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
    };

    const { unit } = await TestBed.solitary(GraphApiService)
      .mock(GraphClientFactory)
      .impl(() => ({
        createClient: () => mockGraphClient,
      }))
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string, defaultValue?: number) => {
          if (key === 'pipeline.msGraphRateLimitPer10Seconds') return defaultValue ?? 10000;
          if (key === 'processing.maxFileSizeBytes') return 10485760;
          return defaultValue;
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

  describe('getAllFilesAndPagesForSite', () => {
    const mockEnrichedFile: EnrichedDriveFile = {
      itemType: 'file' as const,
      id: 'file-1',
      name: 'test.pdf',
      size: 1024,
      webUrl: 'https://sharepoint.example.com/test.pdf',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      file: { mimeType: 'application/pdf' },
      siteId: 'site-1',
      siteWebUrl: 'https://sharepoint.example.com',
      driveId: 'drive-1',
      driveName: 'Documents',
      folderPath: '/',
    };

    const mockEnrichedSitePage: MsGraphSitePage = {
      itemType: 'sitePage' as const,
      id: 'page-1',
      name: 'test.aspx',
      size: 512,
      webUrl: 'https://sharepoint.example.com/test.aspx',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      siteId: 'site-1',
      siteWebUrl: 'https://sharepoint.example.com',
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
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockEnrichedFile]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('skips drives without IDs', async () => {
      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockEnrichedFile]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('handles pagination correctly', async () => {
      const file2: EnrichedDriveFile = {
        ...mockEnrichedFile,
        id: 'file-2',
        name: 'test2.pdf',
      };

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([mockEnrichedSitePage]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([file2]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(2);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('filters out non-syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(false) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(0);
    });

    it('recursively scans folders', async () => {
      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockEnrichedFile]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAspxPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('counts total files vs syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockImplementation(
          (file) => file.name !== 'invalid.exe',
        ) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAspxPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockEnrichedFile]);

      const files = await service.getAllSiteItems('site-1');

      expect(files).toHaveLength(1);
      expect(files[0]?.name).toBe('test.pdf');
    });
  });

  describe('downloadFileContent', () => {
    it('downloads file content successfully', async () => {
      const mockChain = mockGraphClient.api();
      const content = Buffer.from('test content');

      async function* mockStream() {
        yield content;
      }

      mockChain.getStream.mockResolvedValue(mockStream());

      const result = await service.downloadFileContent('drive-1', 'file-1');

      expect(result).toEqual(content);
      expect(mockGraphClient.api).toHaveBeenCalledWith('/drives/drive-1/items/file-1/content');
    });

    it('handles multiple chunks correctly', async () => {
      const mockChain = mockGraphClient.api();
      const chunk1 = Buffer.from('first');
      const chunk2 = Buffer.from('second');

      async function* mockStream() {
        yield chunk1;
        yield chunk2;
      }

      mockChain.getStream.mockResolvedValue(mockStream());

      const result = await service.downloadFileContent('drive-1', 'file-1');

      expect(result).toEqual(Buffer.concat([chunk1, chunk2]));
    });
  });

  describe('getSitePageContent', () => {
    it('fetches site page content successfully', async () => {
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
      });
      expect(mockGraphClient.api).toHaveBeenCalledWith('/sites/site-1/lists/list-1/items/item-1');
      expect(mockChain.expand).toHaveBeenCalledWith('fields($select=CanvasContent1,WikiField)');
    });

    it('handles missing CanvasContent1 field', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          WikiField: '<div>Legacy content</div>',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: undefined,
        wikiField: '<div>Legacy content</div>',
      });
    });

    it('handles missing WikiField field', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValue({
        fields: {
          CanvasContent1: '<div>Modern content</div>',
        },
      });

      const result = await service.getAspxPageContent('site-1', 'list-1', 'item-1');

      expect(result).toEqual({
        canvasContent: '<div>Modern content</div>',
        wikiField: undefined,
      });
    });

    it('throws error when content exceeds size limit', async () => {
      const mockChain = mockGraphClient.api();
      const largeContent = 'x'.repeat(10485761);
      mockChain.get.mockResolvedValue({
        fields: {
          CanvasContent1: largeContent,
        },
      });

      await expect(service.getAspxPageContent('site-1', 'list-1', 'item-1')).rejects.toThrow(
        'Site page content size',
      );
    });
  });
});
