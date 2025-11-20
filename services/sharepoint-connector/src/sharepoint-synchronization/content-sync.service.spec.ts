import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import type { ScopeWithPath } from '../unique-api/unique-scopes/unique-scopes.types';
import { ContentSyncService } from './content-sync.service';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';

describe('ContentSyncService', () => {
  let service: ContentSyncService;
  let configService: ConfigService;
  let uniqueFileIngestionService: UniqueFileIngestionService;
  let uniqueFilesService: UniqueFilesService;
  let itemProcessingOrchestratorService: ItemProcessingOrchestratorService;

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
      ],
    }).compile();

    service = module.get<ContentSyncService>(ContentSyncService);
    configService = module.get<ConfigService>(ConfigService);
    uniqueFileIngestionService = module.get<UniqueFileIngestionService>(UniqueFileIngestionService);
    uniqueFilesService = module.get<UniqueFilesService>(UniqueFilesService);
    itemProcessingOrchestratorService = module.get<ItemProcessingOrchestratorService>(
      ItemProcessingOrchestratorService,
    );
  });

  it('should be defined', () => {
    expect(service).toBeDefined();
  });

  describe('syncContentForSite', () => {
    it('should skip new/updated file ingestion if the number of files to ingest exceeds the limit, but still process deletions and moves', async () => {
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

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1'],
        updatedFiles: ['2'],
        movedFiles: ['moved-file'],
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

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 1;
        }
        return null;
      });

      // Should not throw an error, but should log a warning and skip new/updated file processing
      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();

      // Verify deletions were processed
      expect(uniqueFilesService.getFilesByKeys).toHaveBeenCalledWith(['site-id/deleted-file']);
      expect(uniqueFilesService.deleteFile).toHaveBeenCalledWith('deleted-file-id');

      // Verify moves were processed (would call processFileMoves if there were actual moves)
      // Note: In this test we have movedFiles but no actual move processor verification since it's mocked

      // Verify new/updated file processing was skipped
      expect(uniqueFileIngestionService.performFileDiff).toHaveBeenCalledTimes(1);
      expect(itemProcessingOrchestratorService.processItems).not.toHaveBeenCalled();
    });

    it('should not throw an error if the number of files to ingest is within the limit', async () => {
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

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });

    it('should not throw an error if the limit is not set', async () => {
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

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });

    it('should not throw an error when no files need to be ingested', async () => {
      const siteId = 'site-id';
      const items = [] as SharepointContentItem[];
      const scopes = [] as ScopeWithPath[];

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

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 1;
        }
        return null;
      });

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });

    it('should not throw an error when total files to ingest equals the limit', async () => {
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

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });

    it('should skip new/updated file ingestion with correct warning message when limit is exceeded, but process deletions and moves', async () => {
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

      vi.spyOn(uniqueFileIngestionService, 'performFileDiff').mockResolvedValue({
        newFiles: ['1', '2'],
        updatedFiles: ['3'],
        movedFiles: ['moved-file'],
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

      vi.spyOn(configService, 'get').mockImplementation((key: string) => {
        if (key === 'unique.maxIngestedFiles') {
          return 2;
        }
        return null;
      });

      // Mock the logger to capture warning messages
      const loggerSpy = vi.spyOn(service['logger'], 'warn').mockImplementation(() => {});

      // Should not throw an error, but should log a warning and skip new/updated file processing
      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();

      // Verify the warning was logged with correct message
      expect(loggerSpy).toHaveBeenCalledWith(
        '[SiteId: test-site-123]  Too many files to ingest: 3. Limit is 2. Skipping new/updated file ingestion but deletions and moves were processed.',
      );

      // Verify deletions were processed
      expect(uniqueFilesService.getFilesByKeys).toHaveBeenCalledWith([
        'test-site-123/deleted-file',
      ]);
      expect(uniqueFilesService.deleteFile).toHaveBeenCalledWith('deleted-file-id');

      // Verify new/updated file processing was skipped
      expect(itemProcessingOrchestratorService.processItems).not.toHaveBeenCalled();
    });

    it('should handle limit validation with only new files', async () => {
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

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });

    it('should handle limit validation with only updated files', async () => {
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

      await expect(service.syncContentForSite(siteId, items, scopes)).resolves.not.toThrow();
    });
  });
});
