import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueAuthService } from '../auth/unique-auth.service';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { SharepointApiService } from '../sharepoint-api/sharepoint-api.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import { SharepointScannerService } from './sharepoint-scanner.service';

describe('SharepointScannerService', () => {
  let service: SharepointScannerService;
  let orchestrator: FileProcessingOrchestratorService;

  beforeEach(async () => {
    const files = [
      {
        id: '1',
        name: 'a.pdf',
        webUrl: 'https://web',
        listItem: { lastModifiedDateTime: new Date().toISOString(), fields: {} },
        parentReference: { siteId: 'site-1', driveId: 'drive-1' },
        file: { mimeType: 'application/pdf' },
      },
    ] as any;

    const { unit, unitRef } = await TestBed.solitary(SharepointScannerService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => (k === 'sharepoint.sites' ? ['site-1'] : undefined)),
      }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .mock(SharepointApiService)
      .impl(() => ({ findAllSyncableFilesForSite: vi.fn().mockResolvedValue(files) }))
      .mock(UniqueApiService)
      .impl(() => ({
        performFileDiff: vi.fn().mockResolvedValue({
          newAndUpdatedFiles: ['sharepoint_file_1'],
          deletedFiles: [],
          movedFiles: [],
        }),
      }))
      .mock(FileProcessingOrchestratorService)
      .impl(() => ({ processFilesForSite: vi.fn().mockResolvedValue(undefined) }))
      .compile();

    service = unit;
    orchestrator = unitRef.get(FileProcessingOrchestratorService) as unknown as FileProcessingOrchestratorService;
  });

  it('scans and triggers processing', async () => {
    await service.scanForWork();
    expect((orchestrator.processFilesForSite as any).mock.calls.length).toBe(1);
  });
});
