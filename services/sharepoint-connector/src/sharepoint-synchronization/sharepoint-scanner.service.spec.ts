import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

describe('SharepointSynchronizationService', () => {
  let service: SharepointSynchronizationService;
  let mockOrchestrator: {
    processFilesForSite: ReturnType<typeof vi.fn>;
  };

  const mockFile: EnrichedDriveItem = {
    id: '1',
    name: 'a.pdf',
    webUrl: 'https://web',
    listItem: { lastModifiedDateTime: new Date().toISOString(), fields: {} },
    parentReference: { siteId: 'site-1', driveId: 'drive-1' },
    file: { mimeType: 'application/pdf' },
    size: 1024,
    siteId: 'site-1',
    siteWebUrl: 'https://sharepoint.example.com/sites/site-1',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/',
    lastModifiedDateTime: new Date().toISOString(),
  };

  beforeEach(async () => {
    mockOrchestrator = {
      processFilesForSite: vi.fn().mockResolvedValue(undefined),
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
      .impl(() => ({ getAllFilesForSite: vi.fn().mockResolvedValue([mockFile]) }))
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
    expect(mockOrchestrator.processFilesForSite).toHaveBeenCalledTimes(1);
  });

  it('prevents overlapping scans', async () => {
    mockOrchestrator.processFilesForSite.mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 100)),
    );

    const scan1 = service.synchronize();
    const scan2 = service.synchronize();

    await Promise.all([scan1, scan2]);

    expect(mockOrchestrator.processFilesForSite).toHaveBeenCalledTimes(1);
  });
});
