import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { DriveItem } from '../msgraph/types/sharepoint.types';
import type { SharepointContentItem } from '../msgraph/types/sharepoint-content-item.interface';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

describe('SharepointSynchronizationService', () => {
  let service: SharepointSynchronizationService;
  let mockOrchestrator: {
    processSiteItems: ReturnType<typeof vi.fn>;
  };

  const mockDriveItem: DriveItem = {
    '@odata.etag': 'etag1',
    id: '1',
    name: 'a.pdf',
    webUrl: 'https://web',
    size: 1024,
    lastModifiedDateTime: new Date().toISOString(),
    parentReference: {
      driveType: 'documentLibrary',
      siteId: 'site-1',
      driveId: 'drive-1',
      id: 'parent1',
      name: 'Documents',
      path: '/drive/root:/',
    },
    file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
    listItem: {
      '@odata.etag': 'etag1',
      id: 'item1',
      eTag: 'etag1',
      createdDateTime: new Date().toISOString(),
      lastModifiedDateTime: new Date().toISOString(),
      webUrl: 'https://web',
      fields: {
        '@odata.etag': 'etag1',
        FinanceGPTKnowledge: false,
        FileLeafRef: 'a.pdf',
        Modified: new Date().toISOString(),
        Created: new Date().toISOString(),
        ContentType: 'Document',
        AuthorLookupId: '1',
        EditorLookupId: '1',
        ItemChildCount: '0',
        FolderChildCount: '0',
      },
    },
  };

  const mockFile: SharepointContentItem = {
    itemType: 'driveItem',
    item: mockDriveItem,
    siteId: 'site-1',
    siteWebUrl: 'https://sharepoint.example.com/sites/site-1',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/',
    fileName: 'a.pdf',
  };

  beforeEach(async () => {
    mockOrchestrator = {
      processSiteItems: vi.fn().mockResolvedValue(undefined),
    };

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => (k === 'sharepoint.siteIds' ? ['site-1'] : undefined)),
      }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .mock(GraphApiService)
      .impl(() => ({ getAllSiteItems: vi.fn().mockResolvedValue([mockFile]) }))
      .mock(UniqueApiService)
      .impl(() => ({
        performFileDiff: vi.fn().mockResolvedValue({
          newAndUpdatedFiles: ['1'],
          deletedFiles: [],
          movedFiles: [],
        }),
      }))
      .mock(FileProcessingOrchestratorService)
      .impl(() => mockOrchestrator)
      .compile();

    service = unit;
  });

  it('scans and triggers processing', async () => {
    await service.synchronize();
    expect(mockOrchestrator.processSiteItems).toHaveBeenCalledTimes(1);
  });

  it('prevents overlapping scans', async () => {
    mockOrchestrator.processSiteItems.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 100)),
    );

    const scan1 = service.synchronize();
    const scan2 = service.synchronize();

    await Promise.all([scan1, scan2]);

    expect(mockOrchestrator.processSiteItems).toHaveBeenCalledTimes(1);
  });
});
