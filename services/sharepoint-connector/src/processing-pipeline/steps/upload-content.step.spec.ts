import { Readable } from 'node:stream';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { Dispatcher } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { GraphApiService } from '../../microsoft-apis/graph/graph-api.service';
import type { DriveItem, ListItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { HttpClientService } from '../../shared/services/http-client.service';
import { createMockSiteConfig } from '../../utils/test-utils/mock-site-config';
import { UniqueFilesService } from '../../unique-api/unique-files/unique-files.service';
import type { ProcessingContext } from '../types/processing-context';
import { UploadContentStep } from './upload-content.step';

describe('UploadContentStep', () => {
  let step: UploadContentStep;
  let mockHttpClientService: HttpClientService;
  let mockUniqueFilesService: UniqueFilesService;
  let mockApiService: GraphApiService;

  const mockDriveItem: DriveItem = {
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
  };

  const mockListItem: ListItem = {
    id: 'f1',
    webUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    createdDateTime: '2024-01-01T00:00:00Z',
    createdBy: {
      user: {
        email: 'test@example.com',
        id: 'user1',
        displayName: 'Test User',
      },
    },
    fields: {
      '@odata.etag': 'etag1',
      FinanceGPTKnowledge: false,
      _ModerationStatus: ModerationStatus.Approved,
      Title: 'Test Page',
      FileSizeDisplay: '512',
      FileLeafRef: 'test.aspx',
    },
  };

  const baseDriveItemContext: ProcessingContext = {
    syncContext: {
      siteConfig: createMockSiteConfig(),
      siteName: 'test-site',
      serviceUserId: 'user-1',
      rootPath: '/Root',
    },
    correlationId: 'c1',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://example.sharepoint.com/sites/test/document.docx',
    mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    targetScopeId: 'scope-1', // forced save
    fileStatus: 'new',
    uploadUrl: 'https://storage.example.com/upload?key=encrypted-key',
    uniqueContentId: 'cont_abc123',
    fileSize: 20791,
    pipelineItem: {
      itemType: 'driveItem' as const,
      item: mockDriveItem,
      siteId: 'bd9c85ee-998f-4665-9c44-577cf5a08a66',
      driveId: 'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
      driveName: 'Documents',
      folderPath: '/Freigegebene Dokumente/test-sharepoint-connector-v2',
      fileName: 'Document.docx',
    },
  };

  const baseListItemContext: ProcessingContext = {
    syncContext: {
      siteConfig: createMockSiteConfig(),
      siteName: 'test-site',
      serviceUserId: 'user-1',
      rootPath: '/Root',
    },
    correlationId: 'c2',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/test/test.aspx',
    mimeType: 'text/html',
    targetScopeId: 'scope-1', // forced save
    fileStatus: 'new',
    uploadUrl: 'https://storage.example.com/upload?key=encrypted-key',
    uniqueContentId: 'cont_def456',
    htmlContent: '<div><h2>Test Page</h2><p>Content</p></div>',
    fileSize: 50,
    pipelineItem: {
      itemType: 'listItem' as const,
      item: mockListItem,
      siteId: 'site-1',
      driveId: 'drive-1',
      driveName: 'SitePages',
      folderPath: '/',
      fileName: 'test.aspx',
    },
  };

  const createMockResponseBody = () =>
    ({
      text: vi.fn().mockResolvedValue(''),
    }) as unknown as Dispatcher.ResponseData['body'];

  beforeEach(async () => {
    const { unit, unitRef } = await TestBed.solitary(UploadContentStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'processing.allowedMimeTypes') {
            return [
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              'text/html',
            ];
          }
          return undefined;
        }),
      }))
      .mock(HttpClientService)
      .impl((stub) => ({
        ...stub(),
        httpAgent: {} as Dispatcher,
        request: vi.fn().mockResolvedValue({
          statusCode: 201,
          body: createMockResponseBody(),
        }),
      }))
      .mock(UniqueFilesService)
      .impl((stub) => ({
        ...stub(),
        deleteFile: vi.fn().mockResolvedValue(undefined),
      }))
      .mock(GraphApiService)
      .impl((stub) => ({
        ...stub(),
        getFileContentStream: vi.fn().mockResolvedValue(Readable.from(Buffer.from('test content'))),
      }))
      .compile();

    step = unit;
    mockHttpClientService = unitRef.get(HttpClientService) as unknown as HttpClientService;
    mockUniqueFilesService = unitRef.get(UniqueFilesService) as unknown as UniqueFilesService;
    mockApiService = unitRef.get(GraphApiService) as unknown as GraphApiService;
  });

  describe('execute', () => {
    describe('driveItem uploads', () => {
      it('streams file content directly to storage', async () => {
        const mockStream = Readable.from(Buffer.from('test file content'));
        vi.mocked(mockApiService.getFileContentStream).mockResolvedValue(mockStream);

        const result = await step.execute({ ...baseDriveItemContext });

        expect(mockApiService.getFileContentStream).toHaveBeenCalledWith(
          'b!7oWcvY-ZZUacRFd89aCKZjWhNFgDOmpNl-ie90bvedU15Nf6hZUDQZwrC8isb7Oq',
          '01JWNC3IM2TIAIFMTM4JHYR6RX3E2REDPW',
        );
        expect(mockHttpClientService.request).toHaveBeenCalledWith(
          'https://storage.example.com/upload?key=encrypted-key',
          expect.objectContaining({
            method: 'PUT',
            body: expect.any(Readable),
          }),
        );
        expect(result.uploadSucceeded).toBe(true);
      });

      it('includes correct headers for upload', async () => {
        await step.execute({ ...baseDriveItemContext });

        expect(mockHttpClientService.request).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            headers: {
              'Content-Type':
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
              'Content-Length': '20791',
              'x-ms-blob-type': 'BlockBlob',
            },
          }),
        );
      });

      it('throws when MIME type is not allowed', async () => {
        const contextWithBadMimeType = {
          ...baseDriveItemContext,
          pipelineItem: {
            ...baseDriveItemContext.pipelineItem,
            item: {
              ...mockDriveItem,
              file: { mimeType: 'application/x-executable' },
            },
          },
        } as ProcessingContext;

        await expect(step.execute(contextWithBadMimeType)).rejects.toThrow(
          'MIME type application/x-executable is not allowed',
        );
      });

      it('throws when MIME type is missing', async () => {
        const contextWithNoMimeType = {
          ...baseDriveItemContext,
          pipelineItem: {
            ...baseDriveItemContext.pipelineItem,
            item: {
              ...mockDriveItem,
              file: undefined,
            },
          },
        } as ProcessingContext;

        await expect(step.execute(contextWithNoMimeType)).rejects.toThrow(
          'MIME type is missing for this item',
        );
      });

      it('throws when upload URL is missing', async () => {
        const contextWithoutUrl = { ...baseDriveItemContext, uploadUrl: undefined };

        await expect(step.execute(contextWithoutUrl)).rejects.toThrow(
          'Upload URL not found - content registration may have failed',
        );
      });

      it('throws on upload failure with non-2xx status', async () => {
        vi.mocked(mockHttpClientService.request).mockResolvedValue({
          statusCode: 500,
          body: {
            text: vi.fn().mockResolvedValue('Internal Server Error'),
          } as unknown as Dispatcher.ResponseData['body'],
        } as unknown as Dispatcher.ResponseData);

        await expect(step.execute({ ...baseDriveItemContext })).rejects.toThrow(
          'Upload failed with status 500',
        );
      });
    });

    describe('listItem uploads', () => {
      it('streams HTML content to storage', async () => {
        const result = await step.execute({ ...baseListItemContext });

        expect(mockHttpClientService.request).toHaveBeenCalledWith(
          'https://storage.example.com/upload?key=encrypted-key',
          expect.objectContaining({
            method: 'PUT',
          }),
        );
        expect(result.uploadSucceeded).toBe(true);
        expect(mockApiService.getFileContentStream).not.toHaveBeenCalled();
      });

      it('includes correct headers for HTML upload', async () => {
        await step.execute({ ...baseListItemContext });

        expect(mockHttpClientService.request).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            headers: {
              'Content-Type': 'text/html',
              'Content-Length': '50',
              'x-ms-blob-type': 'BlockBlob',
            },
          }),
        );
      });

      it('throws when HTML content is missing', async () => {
        const contextWithoutHtml = { ...baseListItemContext, htmlContent: undefined };

        await expect(step.execute(contextWithoutHtml)).rejects.toThrow(
          'HTML content not found - ASPX processing may have failed',
        );
      });

      it('throws when upload URL is missing', async () => {
        const contextWithoutUrl = { ...baseListItemContext, uploadUrl: undefined };

        await expect(step.execute(contextWithoutUrl)).rejects.toThrow(
          'Upload URL not found - content registration may have failed',
        );
      });
    });
  });

  describe('cleanup', () => {
    it('deletes registered content when upload failed', async () => {
      const context: ProcessingContext = {
        ...baseDriveItemContext,
        uploadSucceeded: false,
        uniqueContentId: 'cont_abc123',
      };

      await step.cleanup(context);

      expect(mockUniqueFilesService.deleteFile).toHaveBeenCalledWith('cont_abc123');
    });

    it('does not delete content when upload succeeded', async () => {
      const context: ProcessingContext = {
        ...baseDriveItemContext,
        uploadSucceeded: true,
        uniqueContentId: 'cont_abc123',
      };

      await step.cleanup(context);

      expect(mockUniqueFilesService.deleteFile).not.toHaveBeenCalled();
    });

    it('does not delete when uniqueContentId is missing', async () => {
      const context: ProcessingContext = {
        ...baseDriveItemContext,
        uploadSucceeded: false,
        uniqueContentId: undefined,
      };

      await step.cleanup(context);

      expect(mockUniqueFilesService.deleteFile).not.toHaveBeenCalled();
    });

    it('releases HTML content memory', async () => {
      const context: ProcessingContext = {
        ...baseListItemContext,
        uploadSucceeded: true,
      };

      await step.cleanup(context);

      expect(context.htmlContent).toBeUndefined();
    });

    it('handles delete failure gracefully', async () => {
      vi.mocked(mockUniqueFilesService.deleteFile).mockRejectedValue(new Error('Delete failed'));

      const context: ProcessingContext = {
        ...baseDriveItemContext,
        uploadSucceeded: false,
        uniqueContentId: 'cont_abc123',
      };

      await expect(step.cleanup(context)).resolves.toBeUndefined();
    });
  });

  describe('streaming behavior', () => {
    it('streams large content without buffering entire file in memory', async () => {
      let streamConsumedFully = false;
      let streamChunksRequested = 0;

      const testStream = new Readable({
        read() {
          if (++streamChunksRequested < 100) {
            this.push(Buffer.from(`test content nr ${streamChunksRequested}`));
          } else {
            streamConsumedFully = true;
            this.push(null);
          }
        },
      });

      vi.mocked(mockApiService.getFileContentStream).mockResolvedValue(testStream);

      vi.mocked(mockHttpClientService.request).mockImplementation(async () => {
        // If streaming properly, source stream should NOT be consumed yet
        // If buffering, source stream WILL be fully consumed before upload
        expect(streamConsumedFully).toBe(false);

        return {
          statusCode: 201,
          body: {
            text: vi.fn().mockResolvedValue(''),
          } as unknown as Dispatcher.ResponseData['body'],
        } as unknown as Dispatcher.ResponseData;
      });

      await step.execute({ ...baseDriveItemContext });
    });
  });
});
