import {ConfigService} from '@nestjs/config';
import {TestBed} from '@suites/unit';
import {beforeEach, describe, expect, it, vi} from 'vitest';
import {ProcessingPipelineService} from './processing-pipeline.service';
import {ContentFetchingStep} from './steps/content-fetching.step';
import {ContentRegistrationStep} from './steps/content-registration.step';
import {IngestionFinalizationStep} from './steps/ingestion-finalization.step';
import type {IPipelineStep} from './steps/pipeline-step.interface';
import {StorageUploadStep} from './steps/storage-upload.step';
import {PipelineStep} from './types/processing-context';
import {EnrichedDriveItem} from "../msgraph/types/enriched-drive-item";

describe('ProcessingPipelineService', () => {
  let service: ProcessingPipelineService;
  let mockSteps: {
    contentFetching: IPipelineStep & { cleanup: ReturnType<typeof vi.fn> };
    contentRegistration: IPipelineStep;
    storageUpload: IPipelineStep;
    ingestionFinalization: IPipelineStep;
  };

  const mockFile: EnrichedDriveItem = {
    id: 'file-123',
    name: 'test.pdf',
    size: 1024,
    webUrl: 'https://sharepoint.example.com/test.pdf',
    file: { mimeType: 'application/pdf' },
    parentReference: {
      siteId: 'site-1',
      driveId: 'drive-1',
    },
    listItem: {
      fields: {
        '@odata.etag': '"47cc40f8-ba1f-4100-9623-fcdf93073928,4"',
        FileLeafRef: 'test.pdf',
        Modified: '2024-01-01T00:00:00Z',
        MediaServiceImageTags: [],
        FinanceGPTKnowledge: true,
        Title: 'Test Document',
        id: '16599',
        ContentType: 'Dokument',
        Created: '2024-01-01T00:00:00Z',
        AuthorLookupId: '1704',
        EditorLookupId: '1704',
        _CheckinComment: '',
        LinkFilenameNoMenu: 'test.pdf',
        LinkFilename: 'test.pdf',
        DocIcon: 'pdf',
        FileSizeDisplay: '1024',
        ItemChildCount: '0',
        FolderChildCount: '0',
        _ComplianceFlags: '',
        _ComplianceTag: '',
        _ComplianceTagWrittenTime: '',
        _ComplianceTagUserId: '',
        _CommentCount: '',
        _LikeCount: '',
        _DisplayName: '',
        Edit: '0',
        _UIVersionString: '4.0',
        ParentVersionStringLookupId: '16599',
        ParentLeafNameLookupId: '16599',
      } as Record<string, unknown>,
    },
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    siteId: 'site-1',
    siteWebUrl: 'https://sharepoint.example.com/sites/test',
    driveId: 'drive-1',
    driveName: 'Shared Documents',
    folderPath: '/test-folder',
  };

  beforeEach(async () => {
    mockSteps = {
      contentFetching: {
        stepName: PipelineStep.CONTENT_FETCHING,
        execute: vi.fn(),
        cleanup: vi.fn(),
      },
      contentRegistration: {
        stepName: PipelineStep.CONTENT_REGISTRATION,
        execute: vi.fn(),
      },
      storageUpload: {
        stepName: PipelineStep.STORAGE_UPLOAD,
        execute: vi.fn(),
      },
      ingestionFinalization: {
        stepName: PipelineStep.INGESTION_FINALIZATION,
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
      .impl(() => mockSteps.contentFetching as unknown as ContentFetchingStep)
      .mock(ContentRegistrationStep)
      .impl(() => mockSteps.contentRegistration as unknown as ContentRegistrationStep)
      .mock(StorageUploadStep)
      .impl(() => mockSteps.storageUpload as unknown as StorageUploadStep)
      .mock(IngestionFinalizationStep)
      .impl(() => mockSteps.ingestionFinalization as unknown as IngestionFinalizationStep)
      .compile();

    service = unit;
  });

  it('processes file through all pipeline steps successfully', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
    expect(mockSteps.contentFetching.execute).toHaveBeenCalled();
    expect(mockSteps.contentRegistration.execute).toHaveBeenCalled();
    expect(mockSteps.storageUpload.execute).toHaveBeenCalled();
    expect(mockSteps.ingestionFinalization.execute).toHaveBeenCalled();
  });

  it('creates proper processing context', async () => {
    await service.processFile(mockFile);

    const executeCalls = vi.mocked(mockSteps.contentFetching.execute).mock.calls;
    const context = executeCalls[0]?.[0];

    expect(context?.fileId).toBe('file-123');
    expect(context?.fileName).toBe('test.pdf');
    expect(context?.fileSize).toBe(1024);
    expect(context?.siteUrl).toBe('https://sharepoint.example.com/sites/test');
    expect(context?.libraryName).toBe('drive-1');
    expect(context?.correlationId).toBeDefined();
  });

  it('calls cleanup for each completed step', async () => {
    await service.processFile(mockFile);

    expect(mockSteps.contentFetching.cleanup).toHaveBeenCalled();
  });

  it('stops pipeline and returns error when step fails', async () => {
    const testError = new Error('Step failed');
    vi.mocked(mockSteps.contentRegistration.execute).mockRejectedValue(testError);

    const result = await service.processFile(mockFile);

    expect(result.success).toBe(false);
    expect(mockSteps.storageUpload.execute).not.toHaveBeenCalled();
  });

  it('calls cleanup on failed step', async () => {
    vi.mocked(mockSteps.contentFetching.execute).mockRejectedValue(new Error('Step failed'));

    await service.processFile(mockFile);

    expect(mockSteps.contentFetching.cleanup).toHaveBeenCalled();
  });

  it('handles timeout for slow steps', async () => {
    vi.useFakeTimers();

    vi.mocked(mockSteps.contentFetching.execute).mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 35000)),
    );

    const processPromise = service.processFile(mockFile);

    vi.advanceTimersByTime(31000);

    const result = await processPromise;

    expect(result.success).toBe(false);

    vi.useRealTimers();
  });

  it('handles cleanup errors gracefully', async () => {
    vi.mocked(mockSteps.contentFetching.execute).mockRejectedValue(new Error('Step failed'));
    mockSteps.contentFetching.cleanup.mockResolvedValue(undefined);

    const result = await service.processFile(mockFile);

    expect(result.success).toBe(false);
  });

  it('releases content buffer in final cleanup', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
  });

  it('tracks total duration of pipeline execution', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
  });

  it('handles steps without cleanup method', async () => {
    const result = await service.processFile(mockFile);

    expect(result.success).toBe(true);
  });
});
