import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { INGESTION_SOURCE_KIND } from '../../constants/ingestion.constants';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import type { ListItem } from '../../msgraph/types/sharepoint.types';
import { UniqueApiService } from '../../unique-api/unique-api.service';
import { UniqueAuthService } from '../../unique-api/unique-auth.service';
import type { ProcessingContext } from '../types/processing-context';
import { IngestionFinalizationStep } from './ingestion-finalization.step';

describe('IngestionFinalizationStep', () => {
  let step: IngestionFinalizationStep;

  beforeEach(async () => {
    const { unit } = await TestBed.solitary(IngestionFinalizationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'unique.scopeId') return 'scope-1';
          if (k === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
          return undefined;
        }),
      }))
      .mock(UniqueAuthService)
      .impl(() => ({ getToken: vi.fn().mockResolvedValue('unique-token') }))
      .mock(UniqueApiService)
      .impl(() => ({ finalizeIngestion: vi.fn().mockResolvedValue({ id: 'final-id' }) }))
      .compile();
    step = unit;
  });

  it('finalizes ingestion and updates metadata', async () => {
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
        FileSizeDisplay: '512',
        FileLeafRef: 'test.aspx',
      },
    };

    const context: ProcessingContext = {
      correlationId: 'c1',
      startTime: new Date(),
      knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
      mimeType: 'application/pdf',
      pipelineItem: {
        itemType: 'listItem',
        item: listItem,
        siteId: 'site-1',
        siteWebUrl: 'https://contoso.sharepoint.com/sites/Engineering',
        driveId: 'drive-1',
        driveName: 'Documents',
        folderPath: '/test',
        fileName: 'file.pdf',
      },
      registrationResponse: {
        id: 'reg-id',
        key: 'k',
        byteSize: 10,
        mimeType: 'application/pdf',
        ownerType: UniqueOwnerType.Scope,
        ownerId: 'owner-id',
        writeUrl: 'https://write',
        readUrl: 'https://read',
        createdAt: '2023-01-01T00:00:00Z',
        internallyStoredAt: null,
        source: INGESTION_SOURCE_KIND,
      },
    };

    const result = await step.execute(context);
    expect(result).toEqual(context);
  });
});
