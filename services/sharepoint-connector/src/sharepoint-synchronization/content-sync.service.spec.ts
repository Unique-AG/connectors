import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import { SPC_FILE_DELETED_TOTAL, SPC_FILE_DIFF_EVENTS_TOTAL } from '../metrics';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { ContentSyncService } from './content-sync.service';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';
import type { SharepointSyncContext } from './types';

const mockSiteConfig = {
  siteId: 'site-id',
  syncColumnName: 'TestColumn',
  ingestionMode: IngestionMode.Flat,
  scopeId: 'scope-id',
  maxIngestedFiles: 1000,
  storeInternally: StoreInternallyMode.Enabled,
  syncStatus: 'active' as const,
  syncMode: 'content_only' as const,
};

describe('ContentSyncService', () => {
  let service: ContentSyncService;
  let configService: ConfigService;
  let uniqueFileIngestionService: UniqueFileIngestionService;
  let uniqueFilesService: UniqueFilesService;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      providers: [
        ContentSyncService,
        {
          provide: ConfigService,
          useValue: {
            get: vi.fn(),
          },
        },
        {
          provide: ItemProcessingOrchestratorService,
          useValue: {
            processItems: vi.fn(),
          },
        },
        {
          provide: UniqueFileIngestionService,
          useValue: {
            performFileDiff: vi.fn(),
          },
        },
        {
          provide: UniqueFilesService,
          useValue: {
            getFilesByKeys: vi.fn(),
            deleteFile: vi.fn(),
            getFilesCountForSite: vi.fn(),
          },
        },
        {
          provide: FileMoveProcessor,
          useValue: {
            processFileMoves: vi.fn(),
          },
        },
        {
          provide: ScopeManagementService,
          useValue: {
            determineScopeForItem: vi.fn(),
          },
        },
        {
          provide: SPC_FILE_DIFF_EVENTS_TOTAL,
          useValue: {
            add: vi.fn(),
          },
        },
        {
          provide: SPC_FILE_DELETED_TOTAL,
          useValue: {
            add: vi.fn(),
          },
        },
      ],
    }).compile();

    service = module.get<ContentSyncService>(ContentSyncService);
    configService = module.get<ConfigService>(ConfigService);
    uniqueFileIngestionService = module.get<UniqueFileIngestionService>(UniqueFileIngestionService);
    uniqueFilesService = module.get<UniqueFilesService>(UniqueFilesService);
  });

  it('is defined', () => {
    expect(service).toBeDefined();
  });

  describe('syncContentForSite', () => {
    it('throws an error if the number of files to ingest exceeds the limit', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: { ...mockSiteConfig, maxFilesToIngest: 1 },
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: ['2'],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 1;
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        /Too many files to ingest: 2. Limit is 1. Aborting sync./,
      );
    });

    it('does not throw an error if the number of files to ingest is within the limit', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 2;
        }
        if (key === 'unique.scopeId') {
          return 'scope-id';
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error if the limit is not set', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return undefined;
        }
        if (key === 'unique.scopeId') {
          return 'scope-id';
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error when no files need to be ingested', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: 'existing-file',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/existing-file',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: ['deleted-file'],
      });

      vi.spyOn(uniqueFilesService, 'getFilesByKeys').mockResolvedValue([
        {
          id: 'deleted-file-id',
          key: 'site-id/deleted-file',
          fileAccess: [],
          ownerType: 'user',
          ownerId: 'user-id',
        },
      ]);

      vi.spyOn(uniqueFilesService, 'getFilesCountForSite').mockResolvedValue(5);

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 1;
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error when total files to ingest equals the limit', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 1;
        }
        if (key === 'unique.scopeId') {
          return 'scope-id';
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('throws an error with correct message format when limit is exceeded', async () => {
      const siteId = 'test-site-123';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '3',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/3',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: { ...mockSiteConfig, maxFilesToIngest: 2 },
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1', '2'],
        updatedFiles: ['3'],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 2;
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        '[Site: test-site-123]  Too many files to ingest: 3. Limit is 2. Aborting sync.',
      );
    });

    it('handles limit validation with only new files', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1', '2'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 2;
        }
        if (key === 'unique.scopeId') {
          return 'scope-id';
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('handles limit validation with only updated files', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: ['1', '2'],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 2;
        }
        if (key === 'unique.scopeId') {
          return 'scope-id';
        }
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('throws an error when file diff would delete all files in Unique', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: ['1', '2'],
      });

      vi.spyOn(uniqueFilesService, 'getFilesCountForSite').mockResolvedValue(2);

      vi.spyOn(configService, 'get').mockImplementation(() => null);

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        '[Site: site-id] File diff declares all 2 files stored in Unique as to be deleted. Aborting sync to prevent accidental full deletion.',
      );
    });

    it('throws an error when 0 files are submitted but file diff indicates deletions', async () => {
      const siteId = 'site-id';
      const items = [] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: ['1', '2'],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => null);

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        '[Site: site-id] We submitted 0 files to the file diff and that would result in all 2 files being deleted. Aborting sync to prevent accidental full deletion.',
      );
    });

    it('does not throw an error when partial deletions occur', async () => {
      const siteId = 'site-id';
      const items = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: ['2'],
      });

      vi.spyOn(uniqueFilesService, 'getFilesByKeys').mockResolvedValue([
        {
          id: 'deleted-file-id',
          key: 'site-id/2',
          fileAccess: [],
          ownerType: 'user',
          ownerId: 'user-id',
        },
      ]);

      vi.spyOn(uniqueFilesService, 'getFilesCountForSite').mockResolvedValue(5);

      vi.spyOn(configService, 'get').mockImplementation(() => null);

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error for empty site with no deleted files', async () => {
      const siteId = 'site-id';
      const items = [] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootScopeId: 'scope-id',
        rootPath: '/root',
        siteId,
        siteName: 'test-site',
        siteConfig: mockSiteConfig,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => null);

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });
  });
});
