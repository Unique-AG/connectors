import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { INGESTION_SOURCE_KIND } from '../../constants/ingestion.constants';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import type { ListItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { UniqueFileIngestionService } from '../../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import type { ProcessingContext } from '../types/processing-context';
import { ContentRegistrationStep } from './content-registration.step';

describe('ContentRegistrationStep', () => {
  let step: ContentRegistrationStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(ContentRegistrationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'unique.scopeId') return 'scope-1';
          if (k === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
          return undefined;
        }),
      }))
      .mock(UniqueFileIngestionService)
      .impl(() => ({
        registerContent: vi.fn().mockResolvedValue({
          id: 'cid',
          writeUrl: 'https://upload',
          key: 'k',
          byteSize: 1,
          mimeType: 'application/pdf',
          ownerType: UniqueOwnerType.Scope,
          ownerId: 'o',
          readUrl: 'https://read',
          createdAt: new Date().toISOString(),
          internallyStoredAt: null,
          source: INGESTION_SOURCE_KIND,
        }),
      }))
      .compile();
    step = unit;
  });

  it('registers content and updates context', async () => {
    const listItem: ListItem = {
      id: 'f1',
      webUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      lastModifiedDateTime: '2024-01-01T00:00:00Z',
      createdDateTime: '2024-01-01T00:00:00Z',
      createdBy: {
        user: {
          email: 'user@example.com',
          id: 'user1',
          displayName: 'Test User',
        },
      },
      fields: {
        '@odata.etag': 'etag1',
        FinanceGPTKnowledge: false,
        _ModerationStatus: ModerationStatus.Approved,
        Title: 'Test Title',
        FileSizeDisplay: '1024',
        FileLeafRef: 'test.aspx',
      },
    };

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      scopeId: 'scope-1',
      fileStatus: 'new',
      pipelineItem: {
        itemType: 'listItem',
        item: listItem,
        siteId: 'site',
        siteWebUrl: 'https://contoso.sharepoint.com/sites/Engineering',
        driveId: 'drive',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
    };

    const result = await step.execute(context);
    expect(result.uploadUrl).toBe('https://upload');
    expect(result.uniqueContentId).toBe('cid');
  });
});
