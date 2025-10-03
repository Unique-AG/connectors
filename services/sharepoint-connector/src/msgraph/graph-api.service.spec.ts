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
    listItem: { fields: { Sync: true } as never },
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

    mockFileFilterService = {
      isFileValidForIngestion: vi.fn().mockReturnValue(true),
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
          if (key === 'pipeline.maxFileSizeBytes') return 10485760;
          return defaultValue;
        }),
      }))
      .mock(FileFilterService)
      .impl(() => mockFileFilterService)
      .compile();

    service = unit;
  });

  describe('getAllFilesForSite', () => {
    it('finds syncable files across multiple drives', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get
        .mockResolvedValueOnce({ webUrl: 'https://sharepoint.example.com/sites/site-1' })
        .mockResolvedValueOnce({ value: [mockDrive] })
        .mockResolvedValueOnce({ value: [mockFile] });

      mockFileFilterService.isFileValidForIngestion = vi.fn().mockReturnValue(true);

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(mockGraphClient.api).toHaveBeenCalledWith('/sites/site-1/drives');
    });

    it('skips drives without IDs', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.get
        .mockResolvedValueOnce({ webUrl: 'https://sharepoint.example.com/sites/site-1' })
        .mockResolvedValueOnce({ value: [{ name: 'Invalid Drive' }, mockDrive] })
        .mockResolvedValueOnce({ value: [mockFile] });

      mockFileFilterService.isFileValidForIngestion = vi.fn().mockReturnValue(true);

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
    });

    it('handles pagination correctly', async () => {
      const mockChain = mockGraphClient.api();
      const file2: DriveItem = { ...mockFile, id: 'file-2', name: 'test2.pdf' };

      mockChain.get
        .mockResolvedValueOnce({ webUrl: 'https://sharepoint.example.com/sites/site-1' })
        .mockResolvedValueOnce({ value: [mockDrive] })
        .mockResolvedValueOnce({
          value: [mockFile],
          '@odata.nextLink': '/drives/drive-1/items/root/children?$skiptoken=abc',
        })
        .mockResolvedValueOnce({ value: [file2] });

      mockFileFilterService.isFileValidForIngestion = vi.fn().mockReturnValue(true);

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(2);
      expect(mockChain.get).toHaveBeenCalledTimes(4);
    });

    it('filters out non-syncable files', async () => {
      const mockChain = mockGraphClient.api();
      mockFileFilterService.isFileValidForIngestion = vi.fn().mockReturnValue(false);
      mockChain.get
        .mockResolvedValueOnce({ webUrl: 'https://sharepoint.example.com/sites/site-1' })
        .mockResolvedValueOnce({ value: [mockDrive] })
        .mockResolvedValueOnce({ value: [mockFile] });

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(0);
      expect(mockFileFilterService.isFileValidForIngestion).toHaveBeenCalledWith(mockFile);
    });

    it('recursively scans folders', async () => {
      const mockChain = mockGraphClient.api();
      const folder: DriveItem = {
        id: 'folder-1',
        name: 'Subfolder',
        folder: { childCount: 1 },
        parentReference: { driveId: 'drive-1' },
      };

      mockChain.get
        .mockResolvedValueOnce({ webUrl: 'https://sharepoint.example.com/sites/site-1' })
        .mockResolvedValueOnce({ value: [mockDrive] })
        .mockResolvedValueOnce({ value: [folder] })
        .mockResolvedValueOnce({ value: [mockFile] });

      mockFileFilterService.isFileValidForIngestion = vi.fn().mockReturnValue(true);

      const files = await service.getAllFilesForSite('site-1');

      expect(files).toHaveLength(1);
      expect(mockChain.get).toHaveBeenCalledTimes(4);
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

    it('throws error when file exceeds size limit', async () => {
      const mockChain = mockGraphClient.api();
      const largeChunk = Buffer.alloc(11000000);

      const mockReadableStream = {
        [Symbol.asyncIterator]: async function* () {
          yield largeChunk;
        },
        getReader: vi.fn().mockReturnValue({
          cancel: vi.fn().mockResolvedValue(undefined),
          releaseLock: vi.fn(),
        }),
      };

      mockChain.getStream.mockResolvedValue(mockReadableStream);

      await expect(service.downloadFileContent('drive-1', 'file-1')).rejects.toThrow(
        'File size exceeds maximum limit of 10485760 bytes',
      );
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
