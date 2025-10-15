import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphBatchService } from './graph-batch.service';
import { GraphClientFactory } from './graph-client.factory';

describe('GraphApiService', () => {
  let service: GraphApiService;
  let mockGraphClient: {
    api: ReturnType<typeof vi.fn>;
  };
  let mockFileFilterService: Partial<FileFilterService>;
  let mockGraphBatchService: Partial<GraphBatchService>;

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

    // Default behavior for get() - return empty result to terminate pagination
    mockChain.get.mockResolvedValue({ value: [] });

    mockFileFilterService = {
      isFileValidForIngestion: vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'],
    };

    mockGraphBatchService = {
      fetchSiteMetadata: vi.fn().mockResolvedValue({
        webUrl: 'https://sharepoint.example.com/sites/site-1',
        drives: [mockDrive],
      }),
      fetchMultipleFolderChildren: vi.fn().mockResolvedValue(new Map()),
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
          if (key === 'sharepoint.graphRateLimitPer10Seconds') return defaultValue ?? 10000;
          if (key === 'processing.maxFileSizeBytes') return 10485760;
          return defaultValue;
        }),
      }))
      .mock(FileFilterService)
      .impl(() => mockFileFilterService)
      .mock(GraphBatchService)
      .impl(() => mockGraphBatchService)
      .compile();

    service = unit;

    // Mock the rate limiter to avoid async issues
    // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
    (service as any).makeRateLimitedRequest = vi.fn().mockImplementation(
      // biome-ignore lint/suspicious/noExplicitAny: Generic promise type for mocking
      (requestFn: () => Promise<any>) => requestFn(),
    );
  });

  describe('getAllFilesForSite', () => {
    it('finds syncable files across multiple drives', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValueOnce({ value: [mockFile] });

      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'];

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(mockGraphBatchService.fetchSiteMetadata).toHaveBeenCalledWith('site-1');
    });

    it('skips drives without IDs', async () => {
      mockGraphBatchService.fetchSiteMetadata = vi.fn().mockResolvedValue({
        webUrl: 'https://sharepoint.example.com/sites/site-1',
        drives: [{ name: 'Invalid Drive' }, mockDrive],
      });

      const mockChain = mockGraphClient.api();
      mockChain.get.mockResolvedValueOnce({ value: [mockFile] });

      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'];

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
    });

    it('handles pagination correctly', async () => {
      const mockChain = mockGraphClient.api();
      const file2: DriveItem = { ...mockFile, id: 'file-2', name: 'test2.pdf' };

      mockChain.get
        .mockResolvedValueOnce({
          value: [mockFile],
          '@odata.nextLink': '/drives/drive-1/items/root/children?$skiptoken=abc',
        })
        .mockResolvedValueOnce({ value: [file2] });

      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'];

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(2);
      expect(mockChain.get).toHaveBeenCalledTimes(2);
    });

    it('filters out non-syncable files', async () => {
      const mockChain = mockGraphClient.api();
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(false) as unknown as FileFilterService['isFileValidForIngestion'];
      mockChain.get.mockResolvedValueOnce({ value: [mockFile] });

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(0);
      expect(mockFileFilterService.isFileValidForIngestion).toHaveBeenCalledWith(mockFile);
    });

    it('recursively scans folders using batch operations', async () => {
      const mockChain = mockGraphClient.api();
      const folder: DriveItem = {
        id: 'folder-1',
        name: 'Subfolder',
        folder: { childCount: 1 },
        parentReference: { driveId: 'drive-1' },
      };

      mockChain.get.mockResolvedValueOnce({ value: [folder] });

      mockGraphBatchService.fetchMultipleFolderChildren = vi.fn().mockResolvedValue(
        new Map([['drive-1:folder-1', { value: [mockFile] }]]),
      );

      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'];

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(mockGraphBatchService.fetchMultipleFolderChildren).toHaveBeenCalled();
    });

    it('batches subfolders from multiple parents in parallel', async () => {
      const mockChain = mockGraphClient.api();
      const folderA: DriveItem = {
        id: 'folder-a',
        name: 'Folder A',
        folder: { childCount: 2 },
        parentReference: { driveId: 'drive-1' },
      };
      const folderB: DriveItem = {
        id: 'folder-b',
        name: 'Folder B',
        folder: { childCount: 2 },
        parentReference: { driveId: 'drive-1' },
      };
      const subFolderA1: DriveItem = {
        id: 'subfolder-a1',
        name: 'Subfolder A1',
        folder: { childCount: 0 },
        parentReference: { driveId: 'drive-1' },
      };
      const subFolderA2: DriveItem = {
        id: 'subfolder-a2',
        name: 'Subfolder A2',
        folder: { childCount: 0 },
        parentReference: { driveId: 'drive-1' },
      };
      const subFolderB1: DriveItem = {
        id: 'subfolder-b1',
        name: 'Subfolder B1',
        folder: { childCount: 0 },
        parentReference: { driveId: 'drive-1' },
      };
      const subFolderB2: DriveItem = {
        id: 'subfolder-b2',
        name: 'Subfolder B2',
        folder: { childCount: 0 },
        parentReference: { driveId: 'drive-1' },
      };
      const fileInA1 = { ...mockFile, id: 'file-a1', name: 'file-a1.pdf' };
      const fileInB1 = { ...mockFile, id: 'file-b1', name: 'file-b1.pdf' };

      mockChain.get.mockResolvedValueOnce({ value: [folderA, folderB] });

      const fetchMultipleMock = vi.fn();
      fetchMultipleMock
        .mockResolvedValueOnce(
          new Map([
            ['drive-1:folder-a', { value: [subFolderA1, subFolderA2] }],
            ['drive-1:folder-b', { value: [subFolderB1, subFolderB2] }],
          ]),
        )
        .mockResolvedValueOnce(
          new Map([
            ['drive-1:subfolder-a1', { value: [fileInA1] }],
            ['drive-1:subfolder-a2', { value: [] }],
            ['drive-1:subfolder-b1', { value: [fileInB1] }],
            ['drive-1:subfolder-b2', { value: [] }],
          ]),
        );

      mockGraphBatchService.fetchMultipleFolderChildren = fetchMultipleMock;
      mockFileFilterService.isFileValidForIngestion = vi
        .fn()
        .mockReturnValue(true) as unknown as FileFilterService['isFileValidForIngestion'];

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(2);
      expect(mockGraphBatchService.fetchMultipleFolderChildren).toHaveBeenCalledTimes(2);

      const secondCall = fetchMultipleMock.mock.calls[1][0];
      expect(secondCall).toHaveLength(4);
      expect(secondCall.map((req: { itemId: string }) => req.itemId)).toEqual([
        'subfolder-a1',
        'subfolder-a2',
        'subfolder-b1',
        'subfolder-b2',
      ]);
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
