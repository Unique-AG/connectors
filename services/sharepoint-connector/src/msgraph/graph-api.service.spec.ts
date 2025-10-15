import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphClientFactory } from './graph-client.factory';

describe('GraphApiService', () => {
  let service: GraphApiService;
  let mockGraphClient: {
    api: ReturnType<typeof vi.fn>;
  };
  let mockFileFilterService: Partial<FileFilterService>;

  const mockDrive = { id: 'drive-1', name: 'Documents' };
  const mockFile: DriveItem = {
    id: 'file-1',
    name: 'test.pdf',
    size: 1024,
    file: { mimeType: 'application/pdf' },
    webUrl: 'https://sharepoint.example.com/test.pdf',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    parentReference: { driveId: 'drive-1', siteId: 'site-1' },
    listItem: {
      fields: {
        '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
        FileLeafRef: 'test.pdf',
        Modified: '2024-01-01T00:00:00Z',
        MediaServiceImageTags: [],
        FinanceGPTKnowledge: true,
        id: '16599',
        ContentType: 'Dokument',
        Created: '2024-01-01T00:00:00Z',
        AuthorLookupId: '1704',
        EditorLookupId: '1704',
        _CheckinComment: '',
        LinkFilenameNoMenu: 'test.pdf',
        LinkFilename: 'test.pdf',
        DocIcon: 'pdf',
        FileSizeDisplay: '1024',
        ItemChildCount: '0',
        FolderChildCount: '0',
        _ComplianceFlags: '',
        _ComplianceTag: '',
        _ComplianceTagWrittenTime: '',
        _ComplianceTagUserId: '',
        _CommentCount: '',
        _LikeCount: '',
        _DisplayName: '',
        Edit: '0',
        _UIVersionString: '4.0',
        ParentVersionStringLookupId: '16599',
        ParentLeafNameLookupId: '16599',
      } as Record<string, unknown>,
    },
  };

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
        // Increment counter as the real method would do
        service.requestCount++;
        return requestFn();
      },
    );
  });

  describe('getAllFilesAndPagesForSite', () => {
    it('finds syncable files across multiple drives', async () => {
      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockFile]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAllPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('skips drives without IDs', async () => {
      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockFile]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAllPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('handles pagination correctly', async () => {
      const file2: DriveItem = { ...mockFile, id: 'file-2', name: 'test2.pdf' };

      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([mockFile]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([file2]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      expect(files).toHaveLength(2);
      expect(service.getAllPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('filters out non-syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(false) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      expect(files).toHaveLength(0);
    });

    it('recursively scans folders', async () => {
      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockFile]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(service.getAllPagesForSite).toHaveBeenCalledWith('site-1');
      expect(service.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    });

    it('counts total files vs syncable files', async () => {
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockImplementation(
          (file) => file.name !== 'invalid.exe',
        ) as unknown as FileFilterService['isFileValidForIngestion'];

      vi.spyOn(service, 'getAllPagesForSite').mockResolvedValue([]);
      vi.spyOn(service, 'getAllFilesForSite').mockResolvedValue([mockFile]);

      const files = await service.getAllFilesAndPagesForSite('site-1');

      // Should return only the syncable file
      expect(files).toHaveLength(1);
      expect(files[0]?.name).toBe('test.pdf');
      // Total files found should be 2, syncable should be 1
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
});
