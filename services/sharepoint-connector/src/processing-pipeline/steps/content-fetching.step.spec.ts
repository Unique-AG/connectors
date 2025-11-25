import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../../microsoft-apis/graph/graph-api.service';
import type { DriveItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import type { ProcessingContext } from '../types/processing-context';
import { ContentFetchingStep } from './content-fetching.step';

describe('ContentFetchingStep', () => {
  let step: ContentFetchingStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(ContentFetchingStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'processing.allowedMimeTypes') return ['application/pdf'];
          return undefined;
        }),
      }))
      .mock(GraphApiService)
      .impl((stub) => ({
        ...stub(),
        downloadFileContent: vi.fn().mockResolvedValue(Buffer.from('abc')),
        getAspxPageContent: vi
          .fn()
          .mockResolvedValue({ canvasContent: 'content', wikiField: undefined }),
      }))
      .compile();
    step = unit;
  });

  it('fetches content and sets buffer and size', async () => {
    const driveItem: DriveItem = {
      '@odata.etag': 'etag1',
      id: 'f1',
      name: 'test.pdf',
      webUrl: 'https://sharepoint.example.com/test.pdf',
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
        webUrl: 'https://sharepoint.example.com/test.pdf',
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
          FileLeafRef: 'test.pdf',
          Modified: '2024-01-01T00:00:00Z',
          Created: '2024-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          FileSizeDisplay: '1024',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    };

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://sharepoint.example.com/test.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      currentUserId: 'user-1',
      pipelineItem: {
        itemType: 'driveItem',
        item: driveItem,
        siteId: 'site1',
        siteWebUrl: 'https://sharepoint.example.com',
        driveId: 'drive1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'test.pdf',
      },
    };

    const result = await step.execute(context);
    expect(result.fileSize).toBe(1024);
    expect(Buffer.isBuffer(result.contentBuffer)).toBe(true);
  });
});
