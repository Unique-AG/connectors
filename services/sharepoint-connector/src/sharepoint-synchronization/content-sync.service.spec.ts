import { ConfigService } from '@nestjs/config';
import { Test, TestingModule } from '@nestjs/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ItemProcessingOrchestratorService } from '../processing-pipeline/item-processing-orchestrator.service';
import { UniqueFileIngestionService } from '../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import { UniqueFilesService } from '../unique-api/unique-files/unique-files.service';
import { ContentSyncService } from './content-sync.service';
import { FileMoveProcessor } from './file-move-processor.service';
import { ScopeManagementService } from './scope-management.service';

describe('ContentSyncService', () => {
  let service: ContentSyncService;
  let configService: ConfigService;
  let uniqueFileIngestionService: UniqueFileIngestionService;

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
  });

  it('should be defined', () => {
    expect(service).toBeDefined();
  });

  describe('syncContentForSite', () => {
    it('should throw an error if the number of files to ingest exceeds the limit', async () => {
      const siteId = 'site-id';
      const items: any[] = [
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
      ];
      const scopes: any[] = [];

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

      await expect(service.syncContentForSite(siteId, items, scopes)).rejects.toThrow(
        /Too many files to ingest: 2. Limit is 1. Aborting sync./,
      );
    });

    it('should not throw an error if the number of files to ingest is within the limit', async () => {
      const siteId = 'site-id';
      const items: any[] = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ];
      const scopes: any[] = [];

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
      const items: any[] = [
        {
          itemType: 'driveItem',
          item: {
            id: '1',
            lastModifiedDateTime: '2023-01-01',
            webUrl: 'http://example.com/1',
          },
        },
      ];
      const scopes: any[] = [];

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
  });
});
