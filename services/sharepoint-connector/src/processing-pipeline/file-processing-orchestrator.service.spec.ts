import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { FileDiffResponse } from '../unique-api/unique-api.types';
import { FileProcessingOrchestratorService } from './file-processing-orchestrator.service';
import { ProcessingPipelineService } from './processing-pipeline.service';

describe('FileProcessingOrchestratorService', () => {
  let service: FileProcessingOrchestratorService;
  let mockPipelineService: {
    processFile: ReturnType<typeof vi.fn>;
  };

  const createMockFile = (id: string, siteId: string): DriveItem => ({
    id,
    name: `file-${id}.pdf`,
    size: 1024,
    parentReference: { siteId, driveId: 'drive-1' },
    file: { mimeType: 'application/pdf' },
  });

  beforeEach(async () => {
    mockPipelineService = {
      processFile: vi.fn().mockResolvedValue({ success: true }),
    };

    const { unit } = await TestBed.solitary(FileProcessingOrchestratorService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'pipeline.processingConcurrency') return 3;
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
      createMockFile('file-1', 'site-1'),
      createMockFile('file-2', 'site-1'),
      createMockFile('file-3', 'site-1'),
    ];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['sharepoint_file_file-1', 'sharepoint_file_file-3'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processFilesForSite('site-1', files, diffResult);

    expect(mockPipelineService.processFile).toHaveBeenCalledTimes(2);
    expect(mockPipelineService.processFile).toHaveBeenCalledWith(files[0]);
    expect(mockPipelineService.processFile).toHaveBeenCalledWith(files[2]);
  });

  it('filters files by site ID', async () => {
    const files = [createMockFile('file-1', 'site-1'), createMockFile('file-2', 'site-2')];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['sharepoint_file_file-1', 'sharepoint_file_file-2'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processFilesForSite('site-1', files, diffResult);

    expect(mockPipelineService.processFile).toHaveBeenCalledTimes(1);
    expect(mockPipelineService.processFile).toHaveBeenCalledWith(files[0]);
  });

  it('handles empty file list gracefully', async () => {
    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: [],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processFilesForSite('site-1', [], diffResult);

    expect(mockPipelineService.processFile).not.toHaveBeenCalled();
  });

  it('processes files with configured concurrency', async () => {
    const files = Array.from({ length: 10 }, (_, i) => createMockFile(`file-${i}`, 'site-1'));

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: files.map((f) => `sharepoint_file_${f.id}`),
      deletedFiles: [],
      movedFiles: [],
    };

    let concurrentCalls = 0;
    let maxConcurrentCalls = 0;

    mockPipelineService.processFile.mockImplementation(async () => {
      concurrentCalls++;
      maxConcurrentCalls = Math.max(maxConcurrentCalls, concurrentCalls);
      await new Promise((resolve) => setTimeout(resolve, 10));
      concurrentCalls--;
      return { success: true };
    });

    await service.processFilesForSite('site-1', files, diffResult);

    expect(mockPipelineService.processFile).toHaveBeenCalledTimes(10);
    expect(maxConcurrentCalls).toBeLessThanOrEqual(3);
  });

  it('continues processing even if some files fail', async () => {
    const files = [
      createMockFile('file-1', 'site-1'),
      createMockFile('file-2', 'site-1'),
      createMockFile('file-3', 'site-1'),
    ];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: files.map((f) => `sharepoint_file_${f.id}`),
      deletedFiles: [],
      movedFiles: [],
    };

    mockPipelineService.processFile
      .mockResolvedValueOnce({ success: true })
      .mockRejectedValueOnce(new Error('Processing failed'))
      .mockResolvedValueOnce({ success: true });

    await service.processFilesForSite('site-1', files, diffResult);

    expect(mockPipelineService.processFile).toHaveBeenCalledTimes(3);
  });

  it('does nothing when no files match diff result', async () => {
    const files = [createMockFile('file-1', 'site-1')];

    const diffResult: FileDiffResponse = {
      newAndUpdatedFiles: ['sharepoint_file_other-file'],
      deletedFiles: [],
      movedFiles: [],
    };

    await service.processFilesForSite('site-1', files, diffResult);

    expect(mockPipelineService.processFile).not.toHaveBeenCalled();
  });
});


