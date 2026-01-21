import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestionMode } from '../constants/ingestion.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../sharepoint-synchronization/sharepoint-sync-context.interface';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { ItemProcessingOrchestratorService } from './item-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';

describe('ItemProcessingOrchestratorService', () => {
  let service: ItemProcessingOrchestratorService;
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
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/test/folder',
    fileName: `file-${id}.pdf`,
  });

  beforeEach(async () => {
    mockPipelineService = {
      processItem: vi.fn().mockResolvedValue({ success: true }),
    };

    const { unit } = await TestBed.solitary(ItemProcessingOrchestratorService)
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

  const mockSyncContext: SharepointSyncContext = {
    siteConfig: createMockSiteConfig(),
    siteName: 'test-site',
    serviceUserId: 'test-user-id',
    rootPath: '/Root',
  };

  it('processes all provided files', async () => {
    const newFiles = [createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66')];
    const updatedFiles = [createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66')];

    await service.processItems(mockSyncContext, newFiles, updatedFiles, () => 'test-scope-id');

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(2);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(
      newFiles[0],
      'test-scope-id',
      'new',
      mockSyncContext,
    );
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(
      updatedFiles[0],
      'test-scope-id',
      'updated',
      mockSyncContext,
    );
  });

  it('processes only files for specified site', async () => {
    const newFiles = [createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66')];
    const updatedFiles: SharepointContentItem[] = [];

    await service.processItems(mockSyncContext, newFiles, updatedFiles, () => 'test-scope-id');

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(1);
    expect(mockPipelineService.processItem).toHaveBeenCalledWith(
      newFiles[0],
      'test-scope-id',
      'new',
      mockSyncContext,
    );
  });

  it('handles empty file list gracefully', async () => {
    await service.processItems(mockSyncContext, [], [], () => 'test-scope-id');

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });

  it('processes files with configured concurrency', async () => {
    const newFiles = Array.from({ length: 5 }, (_, i) =>
      createMockFile(`new-file-${i}`, 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    );
    const updatedFiles = Array.from({ length: 5 }, (_, i) =>
      createMockFile(`updated-file-${i}`, 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
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

    await service.processItems(mockSyncContext, newFiles, updatedFiles, () => 'test-scope-id');

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(10);
    expect(maxConcurrentCalls).toBeLessThanOrEqual(3);
  });

  it('continues processing even if some files fail', async () => {
    const newFiles = [
      createMockFile('file-1', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
      createMockFile('file-2', 'bd9c85ee-998f-4665-9c44-577cf5a08a66'),
    ];
    const updatedFiles = [createMockFile('file-3', 'bd9c85ee-998f-4665-9c44-577cf5a08a66')];

    mockPipelineService.processItem
      .mockResolvedValueOnce({ success: true })
      .mockRejectedValueOnce(new Error('Processing failed'))
      .mockResolvedValueOnce({ success: true });

    await service.processItems(mockSyncContext, newFiles, updatedFiles, () => 'test-scope-id');

    expect(mockPipelineService.processItem).toHaveBeenCalledTimes(3);
  });

  it('does nothing when no files are provided', async () => {
    await service.processItems(mockSyncContext, [], [], () => 'test-scope-id');

    expect(mockPipelineService.processItem).not.toHaveBeenCalled();
  });
});
