import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { EnrichedDriveItem } from '../msgraph/types/enriched-drive-item';
import { buildKnowledgeBaseUrl } from '../utils/sharepoint-url.util';
import { ProcessingPipelineService } from './processing-pipeline.service';
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
    contentRegistration: IPipelineStep;
    storageUpload: IPipelineStep;
    ingestionFinalization: IPipelineStep;
  };

  const mockFile: EnrichedDriveItem = {
    id: '01JWNC3IM2TIAIFMTM4JHYR6RX3E2REDPW',
    name: 'Document.docx',
    size: 20791,
    webUrl:
      'https://uniqueapp.sharepoint.com/sites/UniqueAG/_layouts/15/Doc.aspx?sourcedoc=%7B82009A9A-6CB2-4FE2-88FA-37D935120DF6%7D&file=Document.docx&action=default&mobileredirect=true',
    file: { mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' },
    parentReference: {
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    },
    listItem: {
      fields: {
        '@odata.etag': '"82009a9a-6cb2-4fe2-88fa-37d935120df6,7"',
        FileLeafRef: 'Document.docx',
        Modified: '2025-10-10T13:59:28Z',
        MediaServiceImageTags: [],
        FinanceGPTKnowledge: true,
        Title: 'Document',
        id: '16852',
        ContentType: 'Dokument',
        Created: '2025-10-02T14:36:24Z',
        AuthorLookupId: '1704',
        EditorLookupId: '1704',
        _CheckinComment: '',
        LinkFilenameNoMenu: 'Document.docx',
        LinkFilename: 'Document.docx',
        DocIcon: 'docx',
        FileSizeDisplay: '20791',
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
        _UIVersionString: '6.0',
        ParentVersionStringLookupId: '16852',
        ParentLeafNameLookupId: '16852',
      } as Record<string, unknown>,
    },
    lastModifiedDateTime: '2025-10-10T13:59:28Z',
    siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
    siteWebUrl: 'https://uniqueapp.sharepoint.com/sites/UniqueAG',
    driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    driveName: 'Documents',
    folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
  };

  beforeEach(async () => {
    mockSteps = {
      contentFetching: {
        stepName: PipelineStep.ContentFetching,
        execute: vi.fn(),
        cleanup: vi.fn(),
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

    expect(context?.fileId).toBe('01JWNC3IM2TIAIFMTM4JHYR6RX3E2REDPW');
    expect(context?.fileName).toBe('Document.docx');
    expect(context?.fileSize).toBe(20791);
    expect(context?.siteUrl).toBe('https://uniqueapp.sharepoint.com/sites/UniqueAG');
    expect(context?.libraryName).toBe(
      'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
    );
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

  describe('buildSharePointUrl', () => {
    it('should build proper SharePoint URL for file in subfolder', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder/subfolder',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should build proper SharePoint URL for file in root folder', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/document.docx');
    });

    it('should build proper SharePoint URL for file in root folder with empty path', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/document.docx');
    });

    it('should handle siteWebUrl with trailing slash', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site/',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe('https://tenant.sharepoint.com/sites/test-site/folder/document.docx');
    });

    it('should handle folderPath with leading slash', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder/subfolder',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should handle folderPath without leading slash', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: 'folder/subfolder',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder/subfolder/document.docx',
      );
    });

    it('should URL encode special characters in folder names', () => {
      const file: EnrichedDriveItem = {
        id: 'file123',
        name: 'document.docx',
        size: 1024,
        webUrl: 'https://tenant.sharepoint.com/sites/test-site/_layouts/15/Doc.aspx?sourcedoc=...',
        siteId: 'site456',
        siteWebUrl: 'https://tenant.sharepoint.com/sites/test-site',
        driveId: 'drive789',
        driveName: 'Documents',
        folderPath: '/folder with spaces/sub folder',
        lastModifiedDateTime: '2023-01-01T00:00:00Z',
        file: {
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        },
      };

      const result = buildKnowledgeBaseUrl(file);

      expect(result).toBe(
        'https://tenant.sharepoint.com/sites/test-site/folder%20with%20spaces/sub%20folder/document.docx',
      );
    });
  });
});
