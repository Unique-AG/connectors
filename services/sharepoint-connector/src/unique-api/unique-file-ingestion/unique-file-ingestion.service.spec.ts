import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StoreInternallyMode } from '../../constants/store-internally-mode.enum';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { createSmeared } from '../../utils/smeared';
import { IngestionHttpClient } from '../clients/ingestion-http.client';
import { INGESTION_CLIENT } from '../clients/unique-graphql.client';
import { CONTENT_UPSERT_MUTATION } from './unique-file-ingestion.consts';
import { UniqueFileIngestionService } from './unique-file-ingestion.service';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  IngestionFinalizationRequest,
} from './unique-file-ingestion.types';

describe('UniqueFileIngestionService', () => {
  let service: UniqueFileIngestionService;
  let ingestionClientMock: { request: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    ingestionClientMock = {
      request: vi.fn().mockResolvedValue({
        contentUpsert: {
          id: 'content-id',
          writeUrl: 'https://write-url',
        },
      }),
    };

    const { unit } = await TestBed.solitary(UniqueFileIngestionService)
      .mock(INGESTION_CLIENT)
      .impl(() => ingestionClientMock)
      .mock(IngestionHttpClient)
      // biome-ignore lint/suspicious/noExplicitAny: Not testing IngestionHttpClient, mock is unused
      .impl(() => ({}) as any)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'unique') {
            return { storeInternally: StoreInternallyMode.Enabled };
          }
          return undefined;
        }),
      }))
      .compile();

    service = unit;
  });

  it('registerContent should pass metadata to mutation', async () => {
    const request: ContentRegistrationRequest = {
      key: 'item-key',
      title: 'Item Title',
      mimeType: 'application/pdf',
      ownerType: UniqueOwnerType.Scope,
      scopeId: 'scope-1',
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: 'sharepoint',
      sourceName: 'Sharepoint',
      byteSize: 1024,
      storeInternally: true,
      metadata: {
        Author: 'John Doe',
        Modified: '2024-01-01',
      },
    };

    await service.registerContent(request);

    expect(ingestionClientMock.request).toHaveBeenCalledWith(
      CONTENT_UPSERT_MUTATION,
      expect.objectContaining({
        input: expect.objectContaining({
          metadata: {
            Author: 'John Doe',
            Modified: '2024-01-01',
          },
        }),
      }),
    );
  });

  it('finalizeIngestion should pass metadata to mutation', async () => {
    const request: IngestionFinalizationRequest = {
      key: 'item-key',
      title: 'Item Title',
      mimeType: 'application/pdf',
      ownerType: UniqueOwnerType.Scope,
      byteSize: 1024,
      scopeId: 'scope-1',
      sourceOwnerType: UniqueOwnerType.Company,
      sourceName: 'Sharepoint',
      sourceKind: 'sharepoint',
      fileUrl: 'https://file-url',
      storeInternally: true,
      metadata: {
        Author: 'Jane Doe',
        Created: '2024-01-02',
      },
    };

    await service.finalizeIngestion(request);

    expect(ingestionClientMock.request).toHaveBeenCalledWith(
      CONTENT_UPSERT_MUTATION,
      expect.objectContaining({
        input: expect.objectContaining({
          metadata: {
            Author: 'Jane Doe',
            Created: '2024-01-02',
          },
        }),
      }),
    );
  });

  describe('performFileDiff', () => {
    it('preserves path prefix from ingestionServiceBaseUrl when making file-diff request', async () => {
      let capturedPath: string | undefined;
      const mockHttpClient = {
        request: vi.fn().mockImplementation(async (options) => {
          capturedPath = options.path;
          return {
            statusCode: 200,
            body: {
              json: vi.fn().mockResolvedValue({
                newFiles: [],
                updatedFiles: [],
                movedFiles: [],
                deletedFiles: [],
              }),
              text: vi.fn().mockResolvedValue(''),
            },
          };
        }),
      };

      const { unit } = await TestBed.solitary(UniqueFileIngestionService)
        .mock(INGESTION_CLIENT)
        .impl(() => ingestionClientMock)
        .mock(IngestionHttpClient)
        .impl(() => mockHttpClient)
        .mock(ConfigService)
        .impl((stub) => ({
          ...stub(),
          get: vi.fn((key: string) => {
            if (key === 'unique') {
              return { storeInternally: StoreInternallyMode.Enabled };
            }
            if (key === 'unique.ingestionServiceBaseUrl') {
              return 'https://api.unique.app/ingestion';
            }
            return undefined;
          }),
        }))
        .compile();

      const fileList: FileDiffItem[] = [
        {
          key: 'file-key-1',
          url: 'https://example.com/file1',
          updatedAt: '2024-01-01T00:00:00Z',
        },
      ];

      await unit.performFileDiff(fileList, createSmeared('partial-key'));

      expect(capturedPath).toBe('/ingestion/v2/content/file-diff');
      expect(mockHttpClient.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'POST',
          path: '/ingestion/v2/content/file-diff',
        }),
      );
    });

    it('uses correct path when ingestionServiceBaseUrl has no path prefix', async () => {
      let capturedPath: string | undefined;
      const mockHttpClient = {
        request: vi.fn().mockImplementation(async (options) => {
          capturedPath = options.path;
          return {
            statusCode: 200,
            body: {
              json: vi.fn().mockResolvedValue({
                newFiles: [],
                updatedFiles: [],
                movedFiles: [],
                deletedFiles: [],
              }),
              text: vi.fn().mockResolvedValue(''),
            },
          };
        }),
      };

      const { unit } = await TestBed.solitary(UniqueFileIngestionService)
        .mock(INGESTION_CLIENT)
        .impl(() => ingestionClientMock)
        .mock(IngestionHttpClient)
        .impl(() => mockHttpClient)
        .mock(ConfigService)
        .impl((stub) => ({
          ...stub(),
          get: vi.fn((key: string) => {
            if (key === 'unique') {
              return { storeInternally: StoreInternallyMode.Enabled };
            }
            if (key === 'unique.ingestionServiceBaseUrl') {
              return 'https://api.unique.app';
            }
            return undefined;
          }),
        }))
        .compile();

      const fileList: FileDiffItem[] = [
        {
          key: 'file-key-1',
          url: 'https://example.com/file1',
          updatedAt: '2024-01-01T00:00:00Z',
        },
      ];

      await unit.performFileDiff(fileList, createSmeared('partial-key'));

      expect(capturedPath).toBe('/v2/content/file-diff');
      expect(mockHttpClient.request).toHaveBeenCalledWith(
        expect.objectContaining({
          method: 'POST',
          path: '/v2/content/file-diff',
        }),
      );
    });
  });
});
