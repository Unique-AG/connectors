import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { Client } from 'undici';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UNIQUE_HTTP_CLIENT } from '../http-client.tokens';
import { UniqueApiService } from './unique-api.service';

describe('UniqueApiService', () => {
  let service: UniqueApiService;
  let httpClient: Client;

  beforeEach(async () => {
    httpClient = {
      request: vi.fn().mockResolvedValue({
        body: {
          json: vi.fn().mockResolvedValue({
            newAndUpdatedFiles: ['sharepoint_file_1'],
            deletedFiles: [],
            movedFiles: [],
          }),
        },
      }),
    } as unknown as Client;

    const { unit } = await TestBed.solitary(UniqueApiService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'unique.fileDiffUrl') return 'https://ingestion.example.com/api';
          if (key === 'unique.ingestionGraphQLUrl') return 'https://ingestion.example.com/graphql';
          if (key === 'unique.ingestionGraphqlUrl') return 'https://ingestion.example.com/graphql';
          if (key === 'unique.scopeId') return 'scope-1';
          if (key === 'unique.ingestionHttpExtraHeaders') return {};
          return undefined;
        }),
      }))
      .mock(UNIQUE_HTTP_CLIENT)
      .impl(() => httpClient)
      .compile();

    service = unit;
  });

  it('performs file diff', async () => {
    const result = await service.performFileDiff(
      [
        {
          key: 'sharepoint_file_1',
          url: 'https://sp.example.com/a.pdf',
          updatedAt: new Date().toISOString(),
        },
      ],
      'token-123',
      'test-partial-key',
    );
    expect(result.newAndUpdatedFiles).toEqual(['sharepoint_file_1']);
  });

  it('includes extra headers in file diff request', async () => {
    const customHttpClient = {
      request: vi.fn().mockResolvedValue({
        statusCode: 200,
        body: {
          json: vi.fn().mockResolvedValue({
            newAndUpdatedFiles: [],
            deletedFiles: [],
            movedFiles: [],
          }),
        },
      }),
    } as unknown as Client;

    const { unit } = await TestBed.solitary(UniqueApiService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'unique.fileDiffUrl') return 'https://ingestion.example.com/api';
          if (key === 'unique.ingestionGraphqlUrl') return 'https://ingestion.example.com/graphql';
          if (key === 'unique.scopeId') return 'scope-1';
          if (key === 'unique.ingestionHttpExtraHeaders') return { 'x-client-id': 'test-client' };
          return undefined;
        }),
      }))
      .mock(UNIQUE_HTTP_CLIENT)
      .impl(() => customHttpClient)
      .compile();

    await unit.performFileDiff([], 'token-123', 'test-partial-key');

    expect(customHttpClient.request).toHaveBeenCalledWith(
      expect.objectContaining({
        headers: expect.objectContaining({
          'x-client-id': 'test-client',
        }),
      }),
    );
  });
});
