import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../msgraph/graph-api.service';
import type { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { FileProcessingOrchestratorService } from '../processing-pipeline/file-processing-orchestrator.service';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { SharepointSynchronizationService } from './sharepoint-synchronization.service';

describe('SharepointSynchronizationService', () => {
  let service: SharepointSynchronizationService;
  let mockGraphApiService: Partial<GraphApiService>;
  let mockUniqueAuthService: {
    getToken: ReturnType<typeof vi.fn>;
  };
  let mockUniqueApiService: {
    performFileDiff: ReturnType<typeof vi.fn>;
  };
  let mockOrchestrator: {
    processFilesForSite: ReturnType<typeof vi.fn>;
  };

  const mockFile: EnrichedDriveItem = {
    id: 'file-1',
    name: 'document.pdf',
    webUrl: 'https://sharepoint.example.com/document.pdf',
    listItem: { lastModifiedDateTime: '2024-01-01T00:00:00Z' },
    size: 1024,
    siteId: 'site-1',
    siteWebUrl: 'https://sharepoint.example.com/sites/site-1',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: '/',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
  };

  const mockDiffResult: FileDiffResponse = {
    newAndUpdatedFiles: ['site-1/Documents/document.pdf'],
    deletedFiles: [],
    movedFiles: [],
  };

  beforeEach(async () => {
    mockGraphApiService = {
      getAllFilesForSite: vi.fn().mockResolvedValue([mockFile]),
    };

    mockUniqueAuthService = {
      getToken: vi.fn().mockResolvedValue('test-token'),
    };

    mockUniqueApiService = {
      performFileDiff: vi.fn().mockResolvedValue(mockDiffResult),
    };

    mockOrchestrator = {
      processFilesForSite: vi.fn().mockResolvedValue(undefined),
    };

    const { unit } = await TestBed.solitary(SharepointSynchronizationService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.sites') return ['site-1', 'site-2'];
          return undefined;
        }),
      }))
      .mock(UniqueAuthService)
      .impl(() => mockUniqueAuthService)
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(FileProcessingOrchestratorService)
      .impl(() => mockOrchestrator)
      .mock(UniqueApiService)
      .impl(() => mockUniqueApiService)
      .compile();

    service = unit;
  });

  it('synchronizes files from all configured sites', async () => {
    await service.synchronize();

    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledTimes(2);
    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledWith('site-1');
    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledWith('site-2');
  });

  it('performs file diff for discovered files', async () => {
    await service.synchronize();

    expect(mockUniqueApiService.performFileDiff).toHaveBeenCalled();
  });

  it('processes files through orchestrator', async () => {
    await service.synchronize();

    expect(mockOrchestrator.processFilesForSite).toHaveBeenCalledWith(
      'site-1',
      [mockFile],
      mockDiffResult,
    );
  });

  it('skips sites with no files', async () => {
    mockGraphApiService.getAllFilesForSite = vi.fn().mockResolvedValue([]);

    await service.synchronize();

    expect(mockUniqueApiService.performFileDiff).not.toHaveBeenCalled();
    expect(mockOrchestrator.processFilesForSite).not.toHaveBeenCalled();
  });

  it('prevents overlapping scans', async () => {
    mockGraphApiService.getAllFilesForSite = vi
      .fn()
      .mockImplementation(
        () => new Promise((resolve) => setTimeout(() => resolve([mockFile]), 100)),
      );

    const firstScan = service.synchronize();
    const secondScan = service.synchronize();

    await Promise.all([firstScan, secondScan]);

    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledTimes(2);
  });

  it('releases scan lock after completion', async () => {
    await service.synchronize();
    await service.synchronize();

    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledTimes(4);
  });

  it('releases scan lock on error', async () => {
    mockGraphApiService.getAllFilesForSite = vi
      .fn()
      .mockRejectedValueOnce(new Error('API failure'))
      .mockResolvedValue([mockFile]);

    await service.synchronize();
    await service.synchronize();

    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledTimes(4);
  });

  it('continues processing other sites after site error', async () => {
    mockGraphApiService.getAllFilesForSite = vi
      .fn()
      .mockRejectedValueOnce(new Error('Site 1 failed'))
      .mockResolvedValueOnce([mockFile]);

    await service.synchronize();

    expect(mockGraphApiService.getAllFilesForSite).toHaveBeenCalledTimes(2);
    expect(mockOrchestrator.processFilesForSite).toHaveBeenCalledTimes(1);
  });

  it('acquires authentication token before file diff', async () => {
    await service.synchronize();

    expect(mockUniqueAuthService.getToken).toHaveBeenCalled();
    expect(mockUniqueApiService.performFileDiff).toHaveBeenCalledWith(
      expect.anything(),
      'test-token',
      'site-1',
    );
  });

  it('transforms files to diff items correctly', async () => {
    const fileWithAllFields: EnrichedDriveItem = {
      id: 'file-123',
      name: 'report.xlsx',
      webUrl: 'https://sp.example.com/report.xlsx',
      listItem: { lastModifiedDateTime: '2024-02-15T10:30:00Z' },
      size: 2048,
      siteId: 'site-1',
      siteWebUrl: 'https://sp.example.com/sites/site-1',
      driveId: 'drive-1',
      driveName: 'Documents',
      folderPath: '/',
      lastModifiedDateTime: '2024-02-15T10:30:00Z',
    };

    mockGraphApiService.getAllFilesForSite = vi.fn().mockResolvedValue([fileWithAllFields]);

    await service.synchronize();

    expect(mockUniqueApiService.performFileDiff).toHaveBeenCalledWith(
      [
        {
          id: 'file-123',
          name: 'report.xlsx',
          url: 'https://sp.example.com/report.xlsx',
          updatedAt: '2024-02-15T10:30:00Z',
          key: 'site-1/Documents/report.xlsx',
          driveId: 'drive-1',
          siteId: 'site-1',
        },
      ],
      'test-token',
      'site-1',
    );
  });

  it('handles missing lastModifiedDateTime gracefully', async () => {
    const fileWithoutTimestamp: EnrichedDriveItem = {
      id: 'file-2',
      name: 'doc.txt',
      webUrl: 'https://sp.example.com/doc.txt',
      listItem: {},
      size: 1024,
      siteId: 'site-1',
      siteWebUrl: 'https://sp.example.com/sites/site-1',
      driveId: 'drive-1',
      driveName: 'Documents',
      folderPath: '/',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
    };

    mockGraphApiService.getAllFilesForSite = vi.fn().mockResolvedValue([fileWithoutTimestamp]);

    await service.synchronize();

    expect(mockUniqueApiService.performFileDiff).toHaveBeenCalledWith(
      [
        {
          id: 'file-2',
          name: 'doc.txt',
          url: 'https://sp.example.com/doc.txt',
          updatedAt: undefined,
          key: 'site-1/Documents/doc.txt',
          driveId: 'drive-1',
          siteId: 'site-1',
        },
      ],
      'test-token',
      'site-1',
    );
  });

  it('processes multiple files from same site', async () => {
    const files = [
      { ...mockFile, id: 'file-1', name: 'doc1.pdf' },
      { ...mockFile, id: 'file-2', name: 'doc2.pdf' },
      { ...mockFile, id: 'file-3', name: 'doc3.pdf' },
    ];

    mockGraphApiService.getAllFilesForSite = vi.fn().mockResolvedValue(files);

    await service.synchronize();

    expect(mockUniqueApiService.performFileDiff).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ key: 'site-1/Documents/doc1.pdf' }),
        expect.objectContaining({ key: 'site-1/Documents/doc2.pdf' }),
        expect.objectContaining({ key: 'site-1/Documents/doc3.pdf' }),
      ]),
      'test-token',
      'site-1',
    );
  });

  it('handles authentication errors', async () => {
    mockUniqueAuthService.getToken.mockRejectedValue(new Error('Auth failed'));

    await service.synchronize();

    expect(mockOrchestrator.processFilesForSite).not.toHaveBeenCalled();
  });

  it('handles file diff errors', async () => {
    mockUniqueApiService.performFileDiff.mockRejectedValue(new Error('Diff failed'));

    await service.synchronize();

    expect(mockOrchestrator.processFilesForSite).not.toHaveBeenCalled();
  });
});
