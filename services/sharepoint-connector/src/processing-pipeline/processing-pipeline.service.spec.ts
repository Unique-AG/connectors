import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import { StorageUploadStep } from './steps/storage-upload.step';
import type { ProcessingContext } from './types/processing-context';
import { ProcessingPipelineService } from './processing-pipeline.service';

describe('ProcessingPipelineService', () => {
  let service: ProcessingPipelineService;
  let mockSteps: {
    contentFetching: IPipelineStep;
    contentRegistration: IPipelineStep;
    storageUpload: IPipelineStep;
    ingestionFinalization: IPipelineStep;
  };

  const mockFile: DriveItem = {
    id: 'file-123',
    name: 'test.pdf',
    size: 1024,
    webUrl: 'https://sharepoint.example.com/test.pdf',
    file: { mimeType: 'application/pdf' },
    parentReference: {
      siteId: 'site-1',
      driveId: 'drive-1',
    },
    listItem: { fields: { Title: 'Test Document' } as never },
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
  };

  beforeEach(async () => {
    mockSteps = {
      contentFetching: {
        stepName: 'ContentFetching',
        execute: vi.fn(),
        cleanup: vi.fn(),
      },
      contentRegistration: {
        stepName: 'ContentRegistration',
        execute: vi.fn(),
        cleanup: vi.fn(),
      },
      storageUpload: {
        stepName: 'StorageUpload',
        execute: vi.fn(),
      },
      ingestionFinalization: {
        stepName: 'IngestionFinalization',
        execute: vi.fn(),
      },
    };

    const { unit } = await TestBed.solitary(ProcessingPipelineService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'pipeline.stepTimeoutSeconds') return 30;
          return undefined;
        }),
      }))
      .mock(ContentFetchingStep)
      .impl(() => mockSteps.contentFetching)
      .mock(ContentRegistrationStep)
      .impl(() => mockSteps.contentRegistration)
      .mock(StorageUploadStep)
      .impl(() => mockSteps.storageUpload)
      .mock(IngestionFinalizationStep)
      .impl(() => mockSteps.ingestionFinalization)
      .compile();

    service = unit;
  });

  it('processes file through all pipeline steps successfully', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
    expect(result.completedSteps).toEqual([
      'ContentFetching',
      'ContentRegistration',
      'StorageUpload',
      'IngestionFinalization',
    ]);
    expect(mockSteps.contentFetching.execute).toHaveBeenCalled();
    expect(mockSteps.contentRegistration.execute).toHaveBeenCalled();
    expect(mockSteps.storageUpload.execute).toHaveBeenCalled();
    expect(mockSteps.ingestionFinalization.execute).toHaveBeenCalled();
  });

  it('creates proper processing context', async () => {
    await service.processFile(mockFile);

    const executeCalls = vi.mocked(mockSteps.contentFetching.execute).mock.calls;
    const context: ProcessingContext = executeCalls[0][0];

    expect(context.fileId).toBe('file-123');
    expect(context.fileName).toBe('test.pdf');
    expect(context.fileSize).toBe(1024);
    expect(context.siteUrl).toBe('site-1');
    expect(context.libraryName).toBe('drive-1');
    expect(context.correlationId).toBeDefined();
  });

  it('calls cleanup for each completed step', async () => {
    await service.processFile(mockFile);

    expect(mockSteps.contentFetching.cleanup).toHaveBeenCalled();
    expect(mockSteps.contentRegistration.cleanup).toHaveBeenCalled();
  });

  it('stops pipeline and returns error when step fails', async () => {
    const testError = new Error('Step failed');
    vi.mocked(mockSteps.contentRegistration.execute).mockRejectedValue(testError);

    const result = await service.processFile(mockFile);

    expect(result.success).toBe(false);
    expect(result.error).toEqual(testError);
    expect(result.completedSteps).toEqual(['ContentFetching']);
    expect(mockSteps.storageUpload.execute).not.toHaveBeenCalled();
  });

  it('calls cleanup on failed step', async () => {
    vi.mocked(mockSteps.contentRegistration.execute).mockRejectedValue(new Error('Step failed'));

    await service.processFile(mockFile);

    expect(mockSteps.contentRegistration.cleanup).toHaveBeenCalled();
  });

  it(
    'handles timeout for slow steps',
    async () => {
      vi.mocked(mockSteps.contentFetching.execute).mockImplementation(
        () => new Promise((resolve) => setTimeout(resolve, 35000)),
      );

      const result = await service.processFile(mockFile);

      expect(result.success).toBe(false);
      expect(result.error?.message).toContain('timed out');
    },
    40000,
  );

  it('handles cleanup errors gracefully', async () => {
    vi.mocked(mockSteps.contentFetching.cleanup).mockRejectedValue(new Error('Cleanup failed'));

    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
  });

  it('releases content buffer in final cleanup', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
    expect(result.context.contentBuffer).toBeUndefined();
  });

  it('tracks total duration of pipeline execution', async () => {
    const result = await service.processFile(mockFile);

    expect(result.totalDuration).toBeGreaterThanOrEqual(0);
    expect(typeof result.totalDuration).toBe('number');
  });

  it('handles steps without cleanup method', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
  });
});

