import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import type { DriveItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { HttpClientService } from '../../shared/services/http-client.service';
import { UniqueFilesService } from '../../unique-api/unique-files/unique-files.service';
import type { ProcessingContext } from '../types/processing-context';
import { StorageUploadStep } from './storage-upload.step';

describe('StorageUploadStep', () => {
  it('uploads buffer to storage', async () => {
    const mockHttpClientService = {
      request: vi.fn().mockResolvedValue({ statusCode: 200 }),
    };
    const mockUniqueFilesService = {
      deleteFile: vi.fn().mockResolvedValue(true),
    };

    const { unit: step } = await TestBed.solitary(StorageUploadStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'app.logsDiagnosticsDataPolicy') return 'conceal';
          return 'default-value';
        }),
      }))
      .mock(HttpClientService)
      .impl(() => mockHttpClientService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .compile();

    const driveItem: DriveItem = {
      '@odata.etag': 'etag1',
      id: 'f1',
      name: 'file.pdf',
      webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      size: 1024,
      createdDateTime: '2024-01-01T00:00:00Z',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      createdBy: {
        user: {
          email: 'test@example.com',
          id: 'user-1',
          displayName: 'Test User',
        },
      },
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive1',
        id: 'parent1',
        name: 'Documents',
        path: '/drive/root:/test',
        siteId: 'site1',
      },
      file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
      listItem: {
        '@odata.etag': 'etag1',
        id: 'item1',
        eTag: 'etag1',
        createdDateTime: '2024-01-01T00:00:00Z',
        lastModifiedDateTime: '2024-01-01T00:00:00Z',
        webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
        createdBy: {
          user: {
            email: 'test@example.com',
            id: 'user-1',
            displayName: 'Test User',
          },
        },
        fields: {
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          FileLeafRef: 'file.pdf',
          Modified: '2024-01-01T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          FileSizeDisplay: '12345',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    };

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      syncContext: {
        serviceUserId: 'user-1',
        rootScopeId: 'root-scope-1',
        rootPath: '/Root',
        siteId: 'site1',
        siteName: 'test-site',
      },
      pipelineItem: {
        itemType: 'driveItem',
        item: driveItem,
        siteId: 'site1',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
    };

    const result = await step.execute(context);
    expect(result.contentBuffer?.length).toBe(4);
    expect(result.uploadSucceeded).toBe(true);
  });

  it('deletes registered content during cleanup when upload fails', async () => {
    const mockHttpClientService = {
      request: vi.fn().mockResolvedValue({ statusCode: 500, body: { text: vi.fn() } }),
    };
    const mockUniqueFilesService = {
      deleteFile: vi.fn().mockResolvedValue(true),
    };

    const { unit: step } = await TestBed.solitary(StorageUploadStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'app.logsDiagnosticsDataPolicy') return 'conceal';
          return 'default-value';
        }),
      }))
      .mock(HttpClientService)
      .impl(() => mockHttpClientService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .compile();

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      syncContext: {
        serviceUserId: 'user-1',
        rootScopeId: 'root-scope-1',
        rootPath: '/Root',
        siteId: 'site1',
        siteName: 'test-site',
      },
      pipelineItem: {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'f1',
          name: 'file.pdf',
          webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          size: 1024,
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-01-01T00:00:00Z',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive1',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/test',
            siteId: 'site1',
          },
          file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2024-01-01T00:00:00Z',
            lastModifiedDateTime: '2024-01-01T00:00:00Z',
            webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
            createdBy: {
              user: {
                email: 'test@example.com',
                id: 'user-1',
                displayName: 'Test User',
              },
            },
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'file.pdf',
              Modified: '2024-01-01T00:00:00Z',
              Created: '2024-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              FileSizeDisplay: '12345',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
        },
        siteId: 'site1',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
      uniqueContentId: 'content-1',
    };

    await expect(step.execute(context)).rejects.toThrowError();
    await expect(step.cleanup(context)).resolves.toBeUndefined();
    expect(mockUniqueFilesService.deleteFile).toHaveBeenCalledWith('content-1');
  });

  it('skips deletion when upload succeeded', async () => {
    const mockHttpClientService = {
      request: vi.fn().mockResolvedValue({ statusCode: 200 }),
    };
    const mockUniqueFilesService = {
      deleteFile: vi.fn().mockResolvedValue(true),
    };

    const { unit: step } = await TestBed.solitary(StorageUploadStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'app.logsDiagnosticsDataPolicy') return 'conceal';
          return 'default-value';
        }),
      }))
      .mock(HttpClientService)
      .impl(() => mockHttpClientService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .compile();

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      syncContext: {
        serviceUserId: 'user-1',
        rootScopeId: 'root-scope-1',
        rootPath: '/Root',
        siteId: 'site1',
        siteName: 'test-site',
      },
      pipelineItem: {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'f1',
          name: 'file.pdf',
          webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          size: 1024,
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-01-01T00:00:00Z',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive1',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/test',
            siteId: 'site1',
          },
          file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2024-01-01T00:00:00Z',
            lastModifiedDateTime: '2024-01-01T00:00:00Z',
            webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
            createdBy: {
              user: {
                email: 'test@example.com',
                id: 'user-1',
                displayName: 'Test User',
              },
            },
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'file.pdf',
              Modified: '2024-01-01T00:00:00Z',
              Created: '2024-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              FileSizeDisplay: '12345',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
        },
        siteId: 'site1',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
      uniqueContentId: 'content-1',
    };

    await step.execute(context);
    await expect(step.cleanup(context)).resolves.toBeUndefined();
    expect(mockUniqueFilesService.deleteFile).not.toHaveBeenCalled();
  });

  it('logs cleanup errors but continues', async () => {
    const mockHttpClientService = {
      request: vi.fn().mockResolvedValue({ statusCode: 500, body: { text: vi.fn() } }),
    };
    const mockUniqueFilesService = {
      deleteFile: vi.fn().mockRejectedValue(new Error('delete failed')),
    };

    const { unit: step } = await TestBed.solitary(StorageUploadStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'app.logsDiagnosticsDataPolicy') return 'conceal';
          return 'default-value';
        }),
      }))
      .mock(HttpClientService)
      .impl(() => mockHttpClientService)
      .mock(UniqueFilesService)
      .impl(() => mockUniqueFilesService)
      .compile();

    const loggerErrorSpy = vi.spyOn(step['logger'], 'error');

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      syncContext: {
        serviceUserId: 'user-1',
        rootScopeId: 'root-scope-1',
        rootPath: '/Root',
        siteId: 'site1',
        siteName: 'test-site',
      },
      pipelineItem: {
        itemType: 'driveItem',
        item: {
          '@odata.etag': 'etag1',
          id: 'f1',
          name: 'file.pdf',
          webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          size: 1024,
          createdDateTime: '2024-01-01T00:00:00Z',
          lastModifiedDateTime: '2024-01-01T00:00:00Z',
          createdBy: {
            user: {
              email: 'test@example.com',
              id: 'user-1',
              displayName: 'Test User',
            },
          },
          parentReference: {
            driveType: 'documentLibrary',
            driveId: 'drive1',
            id: 'parent1',
            name: 'Documents',
            path: '/drive/root:/test',
            siteId: 'site1',
          },
          file: { mimeType: 'application/pdf', hashes: { quickXorHash: 'hash1' } },
          listItem: {
            '@odata.etag': 'etag1',
            id: 'item1',
            eTag: 'etag1',
            createdDateTime: '2024-01-01T00:00:00Z',
            lastModifiedDateTime: '2024-01-01T00:00:00Z',
            webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
            createdBy: {
              user: {
                email: 'test@example.com',
                id: 'user-1',
                displayName: 'Test User',
              },
            },
            fields: {
              '@odata.etag': 'etag1',
              FinanceGPTKnowledge: false,
              FileLeafRef: 'file.pdf',
              Modified: '2024-01-01T00:00:00Z',
              Created: '2024-01-01T00:00:00Z',
              ContentType: 'Document',
              AuthorLookupId: '1',
              EditorLookupId: '1',
              FileSizeDisplay: '12345',
              ItemChildCount: '0',
              FolderChildCount: '0',
            },
          },
        },
        siteId: 'site1',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      uploadUrl: 'https://upload.example.com',
      contentBuffer: Buffer.from('data'),
      uniqueContentId: 'content-1',
    };

    await expect(step.execute(context)).rejects.toThrowError();
    await expect(step.cleanup(context)).resolves.toBeUndefined();
    expect(loggerErrorSpy).toHaveBeenCalled();
  });
});
