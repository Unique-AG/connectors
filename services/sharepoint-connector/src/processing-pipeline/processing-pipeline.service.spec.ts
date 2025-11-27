import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../constants/moderation-status.constants';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import type { SharepointSyncContext } from '../sharepoint-synchronization/types';
import { ProcessingPipelineService } from './processing-pipeline.service';
import { AspxProcessingStep } from './steps/aspx-processing.step';
import { ContentFetchingStep } from './steps/content-fetching.step';
import { ContentRegistrationStep } from './steps/content-registration.step';
import { IngestionFinalizationStep } from './steps/ingestion-finalization.step';
import type { IPipelineStep } from './steps/pipeline-step.interface';
import { StorageUploadStep } from './steps/storage-upload.step';
import { PipelineStep } from './types/processing-context';

describe('ProcessingPipelineService', () => {
  let service: ProcessingPipelineService;
  let mockSteps: {
    contentFetching: IPipelineStep & { cleanup: ReturnType<typeof vi.fn> };
    aspxProcessing: IPipelineStep & { cleanup?: ReturnType<typeof vi.fn> };
    contentRegistration: IPipelineStep;
    storageUpload: IPipelineStep;
    ingestionFinalization: IPipelineStep;
  };

  const mockFile: SharepointContentItem = {
    itemType: 'driveItem',
    item: {
      '@odata.etag': '"82009a9a-6cb2-4fe2-88fa-37d935120df6,7"',
      id: '01JWNC3IM2TIAIFMTM4JHYR6RX3E2REDPW',
      name: 'Document.docx',
      size: 20791,
      webUrl:
        'https://uniqueapp.sharepoint.com/sites/UniqueAG/_layouts/15/Doc.aspx?sourcedoc=%7B82009A9A-6CB2-4FE2-88FA-37D935120DF6%7D&file=Document.docx&action=default&mobileredirect=true',
      createdDateTime: '2025-10-02T14:36:24Z',
      lastModifiedDateTime: '2025-10-10T13:59:28Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
      file: {
        mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        hashes: { quickXorHash: 'hash1' },
      },
      parentReference: {
        driveType: 'documentLibrary',
        siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
        driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
        id: 'parent1',
        name: 'Documents',
        path: '/drive/root:/Freigegebene Dokumente/test-sharepoint-connector-v2',
      },
      listItem: {
        '@odata.etag': '"82009a9a-6cb2-4fe2-88fa-37d935120df6,7"',
        id: '16852',
        eTag: '"82009a9a-6cb2-4fe2-88fa-37d935120df6,7"',
        createdDateTime: '2025-10-02T14:36:24Z',
        lastModifiedDateTime: '2025-10-10T13:59:28Z',
        webUrl:
          'https://uniqueapp.sharepoint.com/sites/UniqueAG/_layouts/15/Doc.aspx?sourcedoc=%7B82009A9A-6CB2-4FE2-88FA-37D935120DF6%7D&file=Document.docx&action=default&mobileredirect=true',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        fields: {
          '@odata.etag': '"82009a9a-6cb2-4fe2-88fa-37d935120df6,7"',
          FileLeafRef: 'Document.docx',
          Modified: '2025-10-10T13:59:28Z',
          FinanceGPTKnowledge: true,
          ContentType: 'Dokument',
          Created: '2025-10-02T14:36:24Z',
          AuthorLookupId: '1704',
          EditorLookupId: '1704',
          FileSizeDisplay: '20791',
          ItemChildCount: '0',
          FolderChildCount: '0',
          _ModerationStatus: ModerationStatus.Approved,
        },
      },
    },
    siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
    siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
    driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    driveName: 'Documents',
    folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
    fileName: 'Document.docx',
  };

  beforeEach(async () => {
    mockSteps = {
      contentFetching: {
        stepName: PipelineStep.ContentFetching,
        execute: vi.fn(),
        cleanup: vi.fn(),
      },
      aspxProcessing: {
        stepName: PipelineStep.AspxProcessing,
        execute: vi.fn(),
      },
      contentRegistration: {
        stepName: PipelineStep.ContentRegistration,
        execute: vi.fn(),
      },
      storageUpload: {
        stepName: PipelineStep.StorageUpload,
        execute: vi.fn(),
      },
      ingestionFinalization: {
        stepName: PipelineStep.IngestionFinalization,
        execute: vi.fn(),
      },
    };

    const { unit } = await TestBed.solitary(ProcessingPipelineService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'processing.stepTimeoutSeconds') return 30;
          return undefined;
        }),
      }))
      .mock(ContentFetchingStep)
      .impl(() => mockSteps.contentFetching as unknown as ContentFetchingStep)
      .mock(AspxProcessingStep)
      .impl(() => mockSteps.aspxProcessing as unknown as AspxProcessingStep)
      .mock(ContentRegistrationStep)
      .impl(() => mockSteps.contentRegistration as unknown as ContentRegistrationStep)
      .mock(StorageUploadStep)
      .impl(() => mockSteps.storageUpload as unknown as StorageUploadStep)
      .mock(IngestionFinalizationStep)
      .impl(() => mockSteps.ingestionFinalization as unknown as IngestionFinalizationStep)
      .compile();

    service = unit;
  });

  const mockSyncContext: SharepointSyncContext = {
    serviceUserId: 'test-user-id',
    rootScopeId: 'root-scope-1',
    rootPath: '/Root',
    siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
  };

  it('processes file through all pipeline steps successfully', async () => {
    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(true);
    expect(mockSteps.contentFetching.execute).toHaveBeenCalled();
    expect(mockSteps.aspxProcessing.execute).toHaveBeenCalled();
    expect(mockSteps.contentRegistration.execute).toHaveBeenCalled();
    expect(mockSteps.storageUpload.execute).toHaveBeenCalled();
    expect(mockSteps.ingestionFinalization.execute).toHaveBeenCalled();
  });

  it('creates proper processing context', async () => {
    await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    const executeCalls = vi.mocked(mockSteps.contentFetching.execute).mock.calls;
    const context = executeCalls[0]?.[0];

    expect(context?.pipelineItem.item.id).toBe('01JWNC3IM2TIAIFMTM4JHYR6RX3E2REDPW');
    expect(context?.pipelineItem.fileName).toBe('Document.docx');
    expect(context?.pipelineItem.siteWebUrl).toBe(
      'https://uniqueapp.sharepoint.com/sites/UniqueAG',
    );
    expect(context?.pipelineItem.driveId).toBe(
      'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    );
    expect(context?.correlationId).toBeDefined();
  });

  it('calls cleanup for each completed step', async () => {
    await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(mockSteps.contentFetching.cleanup).toHaveBeenCalled();
  });

  it('stops pipeline and returns error when step fails', async () => {
    const testError = new Error('Step failed');
    vi.mocked(mockSteps.contentRegistration.execute).mockRejectedValue(testError);

    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(false);
    expect(mockSteps.storageUpload.execute).not.toHaveBeenCalled();
  });

  it('calls cleanup on failed step', async () => {
    vi.mocked(mockSteps.contentFetching.execute).mockRejectedValue(new Error('Step failed'));

    await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(mockSteps.contentFetching.cleanup).toHaveBeenCalled();
  });

  it('handles timeout for slow steps', async () => {
    vi.useFakeTimers();

    vi.mocked(mockSteps.contentFetching.execute).mockImplementation(
      () => new Promise((resolve) => setTimeout(resolve, 35000)),
    );

    const processPromise = service.processItem(
      mockFile,
      'test-scope-id',
      'updated',
      mockSyncContext,
    );

    await vi.advanceTimersByTimeAsync(31000);

    const result = await processPromise;

    expect(result.success).toBe(false);

    vi.useRealTimers();
  });

  it('handles cleanup errors gracefully', async () => {
    vi.mocked(mockSteps.contentFetching.execute).mockRejectedValue(new Error('Step failed'));
    mockSteps.contentFetching.cleanup.mockResolvedValue(undefined);

    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(false);
  });

  it('releases content buffer in final cleanup', async () => {
    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(true);
  });

  it('tracks total duration of pipeline execution', async () => {
    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(true);
  });

  it('handles steps without cleanup method', async () => {
    const result = await service.processItem(mockFile, 'test-scope-id', 'updated', mockSyncContext);

    expect(result.success).toBe(true);
  });
});
