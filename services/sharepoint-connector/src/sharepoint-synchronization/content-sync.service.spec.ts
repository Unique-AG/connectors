import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SPC_FILE_DELETED_TOTAL, SPC_FILE_DIFF_EVENTS_TOTAL } from '../metrics';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { createSmeared, Smeared } from '../utils/smeared';
import { createMockSiteConfig } from '../utils/test-utils/mock-site-config';
import { ContentSyncService } from './content-sync.service';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';
import type { SharepointSyncContext } from './sharepoint-sync-context.interface';

const mockSiteConfig = createMockSiteConfig({
  maxFilesToIngest: 1000,
});

const defaultSiteId = createSmeared('site-id');

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
      const items = [
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: ['2'],
        movedFiles: [],
        deletedFiles: [],
      });

      const contextWithLimit = {
        ...context,
        siteConfig: { ...context.siteConfig, maxFilesToIngest: 1 },
      };

      await expect(service.syncContentForSite(items, scopes, contextWithLimit)).rejects.toThrow(
        /Too many files to ingest: 2. Limit is 1. Aborting sync./,
      );
    });

    it('does not throw an error if the number of files to ingest is within the limit', async () => {
      const items = [
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      const contextWithLimit = {
        ...context,
        siteConfig: { ...context.siteConfig, maxFilesToIngest: 2 },
      };

      await expect(
        service.syncContentForSite(items, scopes, contextWithLimit),
      ).resolves.not.toThrow();
    });

    it('does not throw an error if the limit is not set', async () => {
      const items = [
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error when no files need to be ingested', async () => {
      const items = [
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
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

      vi.spyOn(configService, 'get').mockImplementation((_key: string) => {
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('does not throw an error when total files to ingest equals the limit', async () => {
      const items = [
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => {
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('throws an error with correct message format when limit is exceeded', async () => {
      const items = [
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '2',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/2',
          },
        },
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: {
          ...mockSiteConfig,
          siteId: new Smeared('test-site-123', false),
          scopeId: 'scope-id',
          maxFilesToIngest: 2,
        },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1', '2'],
        updatedFiles: ['3'],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation((_key: string) => {
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        /\[Site: .+\]\s+Too many files to ingest: 3\. Limit is 2\. Aborting sync\./,
      );
    });

    it('handles limit validation with only new files', async () => {
      const items = [
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1', '2'],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => {
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('handles limit validation with only updated files', async () => {
      const items = [
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: ['1', '2'],
        movedFiles: [],
        deletedFiles: [],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => {
        return null;
      });

      await expect(service.syncContentForSite(items, scopes, context)).resolves.not.toThrow();
    });

    it('throws an error when file diff would delete all files in Unique', async () => {
      const items = [
        {
          siteId: defaultSiteId,
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
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
        /\[Site: .+\] File diff declares all 2 files stored in Unique as to be deleted\. Aborting sync to prevent accidental full deletion\./,
      );
    });

    it('throws an error when 0 files are submitted but file diff indicates deletions', async () => {
      const items = [] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
      };

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: [],
        updatedFiles: [],
        movedFiles: [],
        deletedFiles: ['1', '2'],
      });

      vi.spyOn(configService, 'get').mockImplementation(() => null);

      await expect(service.syncContentForSite(items, scopes, context)).rejects.toThrow(
        /\[Site: .+\] We submitted 0 files to the file diff and that would result in all 2 files being deleted\. Aborting sync to prevent accidental full deletion\./,
      );
    });

    it('does not throw an error when partial deletions occur', async () => {
      const items = [
        {
          siteId: defaultSiteId,
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
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
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
      const items = [] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];
      const context: SharepointSyncContext = {
        serviceUserId: 'user-123',
        rootPath: new Smeared('/root', false),
        siteName: new Smeared('test-site', false),
        siteConfig: { ...mockSiteConfig, scopeId: 'scope-id' },
        isInitialSync: false,
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
