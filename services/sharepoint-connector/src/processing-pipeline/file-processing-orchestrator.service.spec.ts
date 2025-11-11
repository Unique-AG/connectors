import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { FileDiffResponse } from '../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { FileProcessingOrchestratorService } from './file-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';

describe('FileProcessingOrchestratorService', () => {
  let service: FileProcessingOrchestratorService;
  let mockPipelineService: {
    processItem: ReturnType<typeof vi.fn>;
  };

  const createMockFile = (id: string, siteId: string): SharepointContentItem => ({
    itemType: 'driveItem',
    item: {
      '@odata.etag': 'etag1',
      id,
      name: `file-${id}.pdf`,
      webUrl: `https://sharepoint.example.com/sites/test/file-${id}.pdf`,
      size: 1024,
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive-1',
        id: 'parent1',
        name: 'Documents',
        path: '/drive/root:/test/folder',
        siteId,
      },
      file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
      listItem: {
        '@odata.etag': 'etag1',
        id: `item-${id}`,
        eTag: 'etag1',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        webUrl: `https://sharepoint.example.com/sites/test/file-${id}.pdf`,
        fields: {
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          FileLeafRef: `file-${id}.pdf`,
          Modified: '2024-01-01T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    },
    siteId,
    siteWebUrl: 'https://sharepoint.example.com/sites/test',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/test/folder',
    fileName: `file-${id}.pdf`,
  });

  beforeEach(async () => {
    mockPipelineService = {
      processItem: vi.fn().mockResolvedValue({ success: true }),
    };

    const { unit } = await TestBed.solitary(FileProcessingOrchestratorService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'processing.concurrency') return 3;
          return undefined;
        }),
      }))
      .mock(ProcessingPipelineService)
      .impl(() => mockPipelineService)
      .compile();

    service = unit;
  });

  it('processes only files in diff result', async () => {
    const files = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-2', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    ];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['file-1', 'file-3'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processSiteItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files, diffResult);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(2);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[0]);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[2]);
  });

  it('filters files by drive ID', async () => {
    const files = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-2', 'site-2'),
    ];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['file-1'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processSiteItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files, diffResult);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(1);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[0]);
  });

  it('handles empty file list gracefully', async () => {
    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: [],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processSiteItems('site-1', [], diffResult);

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });

  it('processes files with configured concurrency', async () => {
    const files = Array.from({ length: 10 }, (_, i) =>
      createMockFile(`file-${i}`, 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    );

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: files.map((f) => f.item.id),
      deletedFiles: [],
      movedFiles: [],
    };

    let concurrentCalls = 0;
    let maxConcurrentCalls = 0;

    mockPipelineService.processItem.mockImplementation(async () => {
      concurrentCalls++;
      maxConcurrentCalls = Math.max(maxConcurrentCalls, concurrentCalls);
      await new Promise((resolve) => setTimeout(resolve, 10));
      concurrentCalls--;
      return { success: true };
    });

    await service.processSiteItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files, diffResult);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(10);
    expect(maxConcurrentCalls).toBeLessThanOrEqual(3);
  });

  it('continues processing even if some files fail', async () => {
    const files = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-2', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    ];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: files.map((f) => f.item.id),
      deletedFiles: [],
      movedFiles: [],
    };

    mockPipelineService.processItem
      .mockResolvedValueOnce({ success: true })
      .mockRejectedValueOnce(new Error('Processing failed'))
      .mockResolvedValueOnce({ success: true });

    await service.processSiteItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files, diffResult);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(3);
  });

  it('does nothing when no files match diff result', async () => {
    const files = [createMockFile('file-1', 'site-1')];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['sharepoint_file_other-file'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processSiteItems('site-1', files, diffResult);

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });
});
