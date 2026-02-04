import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { INGESTION_SOURCE_KIND } from '../../constants/ingestion.constants';
import { ModerationStatus } from '../../constants/moderation-status.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import type { ListItem } from '../../microsoft-apis/graph/types/sharepoint.types';
import { createMockSiteConfig } from '../../test-utils/mock-site-config';
import { UniqueFileIngestionService } from '../../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import type { ProcessingContext } from '../types/processing-context';
import { ContentRegistrationStep } from './content-registration.step';

describe('ContentRegistrationStep', () => {
  let uniqueFileIngestionServiceMock: { registerContent: ReturnType<typeof vi.fn> };

  const mockWriteUrl = 'https://upload.com?key=dummyKey';
  const mockIngestionServiceBaseUrl = 'https://api.unique.app/ingestion';

  const createMockListItem = (): ListItem => ({
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
  });

  const createMockContext = (): ProcessingContext => ({
    syncContext: {
      siteConfig: createMockSiteConfig(),
      siteName: 'test-site',
      serviceUserId: 'user-1',
      rootPath: '/Root',
    },
    correlationId: 'c1',
    startTime: new Date(),
    knowledgeBaseUrl: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
    mimeType: 'application/pdf',
    targetScopeId: 'scope-1',
    fileStatus: 'new',
    pipelineItem: {
      itemType: 'listItem',
      item: createMockListItem(),
      siteId: 'site',
      driveId: 'drive',
      driveName: 'Documents',
      folderPath: '/test',
      fileName: 'file.pdf',
    },
  });

  beforeEach(() => {
    uniqueFileIngestionServiceMock = {
      registerContent: vi.fn().mockResolvedValue({
        id: 'cid',
        writeUrl: mockWriteUrl,
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
    };
  });

  it('registers content and updates context in external mode', async () => {
    const { unit } = await TestBed.solitary(ContentRegistrationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
          if (k === 'unique.serviceAuthMode') return 'external';
          return undefined;
        }),
      }))
      .mock(UniqueFileIngestionService)
      .impl(() => uniqueFileIngestionServiceMock)
      .compile();

    const context = createMockContext();
    const result = await unit.execute(context);

    expect(result.uploadUrl).toBe(mockWriteUrl);
    expect(result.uniqueContentId).toBe('cid');

    expect(uniqueFileIngestionServiceMock.registerContent).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: {
          // Original fields from the SharePoint item
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          _ModerationStatus: ModerationStatus.Approved,
          Title: 'Test Title',
          FileSizeDisplay: '1024',
          FileLeafRef: 'test.aspx',
          // Additional fields added to match V1 PowerAutomate connector
          Url: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          Path: '/test',
          DriveId: 'drive',
          Link: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          ItemInternalId: 'f1',
          Filename: 'test.aspx',
          ModerationStatus: 0,
          Author: {
            email: 'user@example.com',
            displayName: 'Test User',
            id: 'user1',
          },
        },
      }),
    );
  });

  it('rewrites uploadUrl to ingestion service endpoint in cluster_local mode', async () => {
    const { unit } = await TestBed.solitary(ContentRegistrationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
          if (k === 'unique.serviceAuthMode') return 'cluster_local';
          if (k === 'unique.ingestionServiceBaseUrl') return mockIngestionServiceBaseUrl;
          return undefined;
        }),
      }))
      .mock(UniqueFileIngestionService)
      .impl(() => uniqueFileIngestionServiceMock)
      .compile();

    const context = createMockContext();
    const result = await unit.execute(context);

    expect(result.uploadUrl).toBe(`${mockIngestionServiceBaseUrl}/scoped/upload?key=dummyKey`);
    expect(result.uniqueContentId).toBe('cid');

    expect(uniqueFileIngestionServiceMock.registerContent).toHaveBeenCalledWith(
      expect.objectContaining({
        metadata: {
          '@odata.etag': 'etag1',
          FinanceGPTKnowledge: false,
          _ModerationStatus: ModerationStatus.Approved,
          Title: 'Test Title',
          FileSizeDisplay: '1024',
          FileLeafRef: 'test.aspx',
          Url: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          Path: '/test',
          DriveId: 'drive',
          Link: 'https://contoso.sharepoint.com/sites/Engineering/file.pdf',
          ItemInternalId: 'f1',
          Filename: 'test.aspx',
          ModerationStatus: 0,
          Author: {
            email: 'user@example.com',
            displayName: 'Test User',
            id: 'user1',
          },
        },
      }),
    );
  });

  it('locks down file access when only scopes inheritance is enabled', async () => {
    const { unit } = await TestBed.solitary(ContentRegistrationStep)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((k: string) => {
          if (k === 'sharepoint.baseUrl') return 'https://contoso.sharepoint.com';
          if (k === 'unique.serviceAuthMode') return 'external';
          return undefined;
        }),
      }))
      .mock(UniqueFileIngestionService)
      .impl(() => uniqueFileIngestionServiceMock)
      .compile();

    const context = createMockContext();
    const updatedSiteConfig = createMockSiteConfig({
      syncMode: 'content_only',
      permissionsInheritanceMode: 'inherit_scopes', // inheritScopes: true, inheritFiles: false
    });
    context.syncContext.siteConfig = updatedSiteConfig;
    context.fileStatus = 'new';
    context.syncContext.serviceUserId = 'user-1';

    await unit.execute(context);

    expect(uniqueFileIngestionServiceMock.registerContent).toHaveBeenCalledWith(
      expect.objectContaining({
        fileAccess: ['u:user-1R', 'u:user-1W', 'u:user-1M'],
      }),
    );
  });
});
