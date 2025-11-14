import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestionMode } from '../constants/ingestion.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ScopeManagementService } from '../sharepoint-synchronization/scope-management.service';
import { ItemProcessingOrchestratorService } from './item-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';

describe('ItemProcessingOrchestratorService', () => {
  let service: ItemProcessingOrchestratorService;
  let mockPipelineService: {
    processItem: ReturnType<typeof vi.fn>;
  };
  let mockScopeManagementService: {
    buildItemIdToScopeIdMap: ReturnType<typeof vi.fn>;
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
          FileSizeDisplay: '12345',
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

    mockScopeManagementService = {
      buildItemIdToScopeIdMap: vi.fn().mockReturnValue(new Map()),
    };

    const { unit } = await TestBed.solitary(ItemProcessingOrchestratorService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'processing.concurrency') return 3;
          if (key === 'unique.ingestionMode') return IngestionMode.Flat;
          if (key === 'unique.scopeId') return 'test-scope-id';
          return undefined;
        }),
      }))
      .mock(ProcessingPipelineService)
      .impl(() => mockPipelineService)
      .mock(ScopeManagementService)
      .impl(() => mockScopeManagementService)
      .compile();

    service = unit;
  });

  it('processes all provided files', async () => {
    const files = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    ];

    await service.processItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(2);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[0], 'test-scope-id');
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[1], 'test-scope-id');
  });

  it('processes only files for specified site', async () => {
    const files = [createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66')];

    await service.processItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(1);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(files[0], 'test-scope-id');
  });

  it('handles empty file list gracefully', async () => {
    await service.processItems('site-1', []);

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });

  it('processes files with configured concurrency', async () => {
    const files = Array.from({ length: 10 }, (_, i) =>
      createMockFile(`file-${i}`, 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    );

    let concurrentCalls = 0;
    let maxConcurrentCalls = 0;

    mockPipelineService.processItem.mockImplementation(async () => {
      concurrentCalls++;
      maxConcurrentCalls = Math.max(maxConcurrentCalls, concurrentCalls);
      await new Promise((resolve) => setTimeout(resolve, 10));
      concurrentCalls--;
      return { success: true };
    });

    await service.processItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(10);
    expect(maxConcurrentCalls).toBeLessThanOrEqual(3);
  });

  it('continues processing even if some files fail', async () => {
    const files = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-2', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    ];

    mockPipelineService.processItem
      .mockResolvedValueOnce({ success: true })
      .mockRejectedValueOnce(new Error('Processing failed'))
      .mockResolvedValueOnce({ success: true });

    await service.processItems('bd9c85ee-998f-4665-9c44-577cf5a08a66', files);

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(3);
  });

  it('does nothing when no files are provided', async () => {
    await service.processItems('site-1', []);

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });
});
