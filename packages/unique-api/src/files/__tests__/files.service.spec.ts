import { describe, expect, it, vi } from 'vitest';
import type { UniqueGraphqlClient } from '../../clients/unique-graphql.client';
import {
  PAGINATED_CONTENT_IDS_QUERY,
  PAGINATED_CONTENT_QUERY,
  type PaginatedContentIdsQueryResult,
  type PaginatedContentQueryResult,
} from '../files.queries';
import { FilesService } from '../files.service';
import type { UniqueFile } from '../files.types';

const mockLogger = vi.hoisted(() => ({
  log: vi.fn(),
  warn: vi.fn(),
  error: vi.fn(),
  debug: vi.fn(),
}));

vi.mock('@nestjs/common', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nestjs/common')>();
  return {
    ...actual,
    Logger: vi.fn().mockImplementation(() => mockLogger),
  };
});

function createMockIngestionClient() {
  return {
    request: vi.fn(),
  } as unknown as UniqueGraphqlClient;
}

function createBatchResponse(ids: string[]): PaginatedContentIdsQueryResult {
  return {
    paginatedContent: {
      nodes: ids.map((id) => ({ id })),
      totalCount: ids.length,
    },
  };
}

function createFile(key: string): UniqueFile {
  return {
    id: `content-${key}`,
    fileAccess: [],
    key,
    ownerType: 'SCOPE',
    ownerId: 'scope-1',
    byteSize: 1,
    expiresAt: null,
    ingestionState: 'FINISHED',
    metadata: null,
  };
}

function createContentResponse(keys: string[]): PaginatedContentQueryResult {
  return { paginatedContent: { nodes: keys.map(createFile) } };
}

function createKeys(count: number, offset = 0): string[] {
  return Array.from({ length: count }, (_, i) => `key-${offset + i}`);
}

function requestedKeys(client: UniqueGraphqlClient, callIndex: number): string[] {
  const [, variables] = vi.mocked(client.request).mock.calls[callIndex] as [
    unknown,
    { where: { key: { in: string[] } } },
  ];
  return variables.where.key.in;
}

describe('FilesService', () => {
  describe('getByKeys', () => {
    it('returns an empty array without querying when no keys are given', async () => {
      const client = createMockIngestionClient();

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys([]);

      expect(result).toEqual([]);
      expect(client.request).not.toHaveBeenCalled();
    });

    it('sends a single request when the key count is below the chunk size', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(99);
      vi.mocked(client.request).mockResolvedValueOnce(createContentResponse(keys));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys(keys);

      expect(result).toHaveLength(99);
      expect(client.request).toHaveBeenCalledTimes(1);
      expect(client.request).toHaveBeenCalledWith(PAGINATED_CONTENT_QUERY, {
        skip: 0,
        take: 100,
        where: { key: { in: keys } },
      });
    });

    it('sends a single request when the key count is exactly the chunk size', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(100);
      vi.mocked(client.request).mockResolvedValueOnce(createContentResponse(keys.slice(0, 40)));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys(keys);

      expect(result).toHaveLength(40);
      expect(client.request).toHaveBeenCalledTimes(1);
      expect(requestedKeys(client, 0)).toEqual(keys);
    });

    it('splits the key list into chunks and aggregates the results', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(250);
      vi.mocked(client.request)
        .mockResolvedValueOnce(createContentResponse(keys.slice(0, 10)))
        .mockResolvedValueOnce(createContentResponse(keys.slice(100, 120)))
        .mockResolvedValueOnce(createContentResponse(keys.slice(200, 205)));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys(keys);

      expect(client.request).toHaveBeenCalledTimes(3);
      expect(requestedKeys(client, 0)).toEqual(keys.slice(0, 100));
      expect(requestedKeys(client, 1)).toEqual(keys.slice(100, 200));
      expect(requestedKeys(client, 2)).toEqual(keys.slice(200, 250));
      expect(result.map((file) => file.key)).toEqual([
        ...keys.slice(0, 10),
        ...keys.slice(100, 120),
        ...keys.slice(200, 205),
      ]);
    });

    it('never sends more keys than the chunk size in one request', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(500);
      vi.mocked(client.request).mockResolvedValue(createContentResponse([]));

      const service = new FilesService(client, mockLogger as never);
      await service.getByKeys(keys);

      const sentKeyCounts = vi
        .mocked(client.request)
        .mock.calls.map((_call, index) => requestedKeys(client, index).length);
      expect(Math.max(...sentKeyCounts)).toBeLessThanOrEqual(100);
      expect(sentKeyCounts).toHaveLength(5);
    });

    it('paginates within a chunk when a chunk matches more content than one page', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(100);
      vi.mocked(client.request)
        .mockResolvedValueOnce(createContentResponse(keys))
        .mockResolvedValueOnce(createContentResponse(createKeys(30, 1000)));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys(keys);

      expect(result).toHaveLength(130);
      expect(client.request).toHaveBeenCalledTimes(2);
      expect(client.request).toHaveBeenNthCalledWith(2, PAGINATED_CONTENT_QUERY, {
        skip: 100,
        take: 100,
        where: { key: { in: keys } },
      });
    });

    it('restarts pagination at skip 0 for each chunk', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(150);
      vi.mocked(client.request)
        .mockResolvedValueOnce(createContentResponse(keys.slice(0, 5)))
        .mockResolvedValueOnce(createContentResponse(keys.slice(100, 105)));

      const service = new FilesService(client, mockLogger as never);
      await service.getByKeys(keys);

      expect(client.request).toHaveBeenNthCalledWith(1, PAGINATED_CONTENT_QUERY, {
        skip: 0,
        take: 100,
        where: { key: { in: keys.slice(0, 100) } },
      });
      expect(client.request).toHaveBeenNthCalledWith(2, PAGINATED_CONTENT_QUERY, {
        skip: 0,
        take: 100,
        where: { key: { in: keys.slice(100, 150) } },
      });
    });

    it('deduplicates keys so a repeated key is not fetched twice', async () => {
      const client = createMockIngestionClient();
      vi.mocked(client.request).mockResolvedValueOnce(createContentResponse(['key-a', 'key-b']));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getByKeys(['key-a', 'key-b', 'key-a']);

      expect(client.request).toHaveBeenCalledTimes(1);
      expect(requestedKeys(client, 0)).toEqual(['key-a', 'key-b']);
      expect(result.map((file) => file.key)).toEqual(['key-a', 'key-b']);
    });
  });

  describe('getContentIdsByScope', () => {
    it('returns all ids in a single batch when results fit within batch size', async () => {
      const client = createMockIngestionClient();
      vi.mocked(client.request).mockResolvedValueOnce(
        createBatchResponse(['id-1', 'id-2', 'id-3']),
      );

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getContentIdsByScope('scope-1');

      expect(result).toEqual(['id-1', 'id-2', 'id-3']);
      expect(client.request).toHaveBeenCalledTimes(1);
    });

    it('paginates when results exceed batch size', async () => {
      const client = createMockIngestionClient();
      const firstBatch = Array.from({ length: 100 }, (_, i) => `id-${i}`);
      const secondBatch = Array.from({ length: 50 }, (_, i) => `id-${100 + i}`);

      vi.mocked(client.request)
        .mockResolvedValueOnce(createBatchResponse(firstBatch))
        .mockResolvedValueOnce(createBatchResponse(secondBatch));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getContentIdsByScope('scope-1');

      expect(result).toHaveLength(150);
      expect(result[0]).toBe('id-0');
      expect(result[99]).toBe('id-99');
      expect(result[100]).toBe('id-100');
      expect(result[149]).toBe('id-149');
      expect(client.request).toHaveBeenCalledTimes(2);
      expect(client.request).toHaveBeenNthCalledWith(2, PAGINATED_CONTENT_IDS_QUERY, {
        skip: 100,
        take: 100,
        where: { ownerId: { equals: 'scope-1' }, ownerType: { equals: 'SCOPE' } },
      });
    });

    it('stops paginating when a batch returns exactly batch size followed by empty', async () => {
      const client = createMockIngestionClient();
      const fullBatch = Array.from({ length: 100 }, (_, i) => `id-${i}`);

      vi.mocked(client.request)
        .mockResolvedValueOnce(createBatchResponse(fullBatch))
        .mockResolvedValueOnce(createBatchResponse([]));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getContentIdsByScope('scope-1');

      expect(result).toHaveLength(100);
      expect(client.request).toHaveBeenCalledTimes(2);
    });

    it('returns empty array when scope has no content', async () => {
      const client = createMockIngestionClient();
      vi.mocked(client.request).mockResolvedValueOnce(createBatchResponse([]));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getContentIdsByScope('scope-1');

      expect(result).toEqual([]);
      expect(client.request).toHaveBeenCalledTimes(1);
    });
  });

  describe('getIdsByScopeAndMetadataKey', () => {
    it('requests paginated ids with metadata filter', async () => {
      const client = createMockIngestionClient();
      vi.mocked(client.request).mockResolvedValueOnce(createBatchResponse(['id-1', 'id-2']));

      const service = new FilesService(client, mockLogger as never);
      const result = await service.getIdsByScopeAndMetadataKey(
        'scope-1',
        'sourceDocumentId',
        'doc-123',
      );

      expect(result).toEqual(['id-1', 'id-2']);
      expect(client.request).toHaveBeenCalledWith(PAGINATED_CONTENT_IDS_QUERY, {
        skip: 0,
        take: 100,
        where: {
          ownerId: { equals: 'scope-1' },
          ownerType: { equals: 'SCOPE' },
          metadata: {
            path: ['sourceDocumentId'],
            equals: 'doc-123',
          },
        },
      });
    });
  });
});
