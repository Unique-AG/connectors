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
          if (key === 'uniqueApi.ingestionUrl') return 'https://ingestion.example.com';
          if (key === 'uniqueApi.ingestionGraphQLUrl') return 'https://ingestion.example.com/graphql';
          if (key === 'uniqueApi.scopeId') return 'scope-1';
          if (key === 'uniqueApi.fileDiffBasePath') return 'https://app.example.com/';
          if (key === 'uniqueApi.fileDiffPartialKey') return 'sharepoint/default';
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
          id: '1',
          name: 'a.pdf',
          url: 'https://sp.example.com/a.pdf',
          updatedAt: new Date().toISOString(),
          key: 'sharepoint_file_1',
        },
      ],
      'token-123',
    );
    expect(result.newAndUpdatedFiles).toEqual(['sharepoint_file_1']);
  });
});
