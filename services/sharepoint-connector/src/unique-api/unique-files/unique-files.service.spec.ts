import { describe, expect, it, vi } from 'vitest';
import type { UniqueGraphqlClient } from '../clients/unique-graphql.client';
import { PAGINATED_CONTENT_QUERY, PaginatedContentQueryResult } from './unique-files.consts';
import { UniqueFilesService } from './unique-files.service';
import { UniqueFile } from './unique-files.types';

function createMockIngestionClient() {
  return { request: vi.fn() } as unknown as UniqueGraphqlClient;
}

function createFile(key: string): UniqueFile {
  return {
    id: `content-${key}`,
    fileAccess: [],
    key,
    ownerType: 'SCOPE',
    ownerId: 'scope-1',
  };
}

function createContentResponse(keys: string[]): PaginatedContentQueryResult {
  return { paginatedContent: { nodes: keys.map(createFile) } };
}

function createKeys(count: number, offset = 0): string[] {
  return Array.from({ length: count }, (_, i) => `site-1/file-${offset + i}`);
}

function requestedKeys(client: UniqueGraphqlClient, callIndex: number): string[] {
  const [, variables] = vi.mocked(client.request).mock.calls[callIndex] as [
    unknown,
    { where: { key: { in: string[] } } },
  ];
  return variables.where.key.in;
}

describe('UniqueFilesService', () => {
  describe('getFilesByKeys', () => {
    it('returns an empty array without querying when no keys are given', async () => {
      const client = createMockIngestionClient();

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys([]);

      expect(result).toEqual([]);
      expect(client.request).not.toHaveBeenCalled();
    });

    it('sends a single request when the key count is below the chunk size', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(99);
      vi.mocked(client.request).mockResolvedValueOnce(createContentResponse(keys));

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys(keys);

      expect(result).toHaveLength(99);
      expect(client.request).toHaveBeenCalledTimes(1);
      expect(client.request).toHaveBeenCalledWith(
        PAGINATED_CONTENT_QUERY,
        { skip: 0, take: 100, where: { key: { in: keys } } },
        { logSafeKeys: ['skip', 'take'] },
      );
    });

    it('sends a single request when the key count is exactly the chunk size', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(100);
      vi.mocked(client.request).mockResolvedValueOnce(createContentResponse(keys.slice(0, 40)));

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys(keys);

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

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys(keys);

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

    it('never sends more keys than the chunk size in one request for a full Graph page', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(300);
      vi.mocked(client.request).mockResolvedValue(createContentResponse([]));

      const service = new UniqueFilesService(client);
      await service.getFilesByKeys(keys);

      const sentKeyCounts = vi
        .mocked(client.request)
        .mock.calls.map((_call, index) => requestedKeys(client, index).length);
      expect(sentKeyCounts).toEqual([100, 100, 100]);
    });

    it('paginates within a chunk when a chunk matches more content than one page', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(100);
      vi.mocked(client.request)
        .mockResolvedValueOnce(createContentResponse(keys))
        .mockResolvedValueOnce(createContentResponse(createKeys(30, 1000)));

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys(keys);

      expect(result).toHaveLength(130);
      expect(client.request).toHaveBeenCalledTimes(2);
      expect(client.request).toHaveBeenNthCalledWith(
        2,
        PAGINATED_CONTENT_QUERY,
        { skip: 100, take: 100, where: { key: { in: keys } } },
        { logSafeKeys: ['skip', 'take'] },
      );
    });

    it('restarts pagination at skip 0 for each chunk', async () => {
      const client = createMockIngestionClient();
      const keys = createKeys(150);
      vi.mocked(client.request)
        .mockResolvedValueOnce(createContentResponse(keys.slice(0, 5)))
        .mockResolvedValueOnce(createContentResponse(keys.slice(100, 105)));

      const service = new UniqueFilesService(client);
      await service.getFilesByKeys(keys);

      expect(client.request).toHaveBeenNthCalledWith(
        1,
        PAGINATED_CONTENT_QUERY,
        { skip: 0, take: 100, where: { key: { in: keys.slice(0, 100) } } },
        { logSafeKeys: ['skip', 'take'] },
      );
      expect(client.request).toHaveBeenNthCalledWith(
        2,
        PAGINATED_CONTENT_QUERY,
        { skip: 0, take: 100, where: { key: { in: keys.slice(100, 150) } } },
        { logSafeKeys: ['skip', 'take'] },
      );
    });

    it('deduplicates keys so a repeated key is not fetched twice', async () => {
      const client = createMockIngestionClient();
      vi.mocked(client.request).mockResolvedValueOnce(
        createContentResponse(['site-1/a', 'site-1/b']),
      );

      const service = new UniqueFilesService(client);
      const result = await service.getFilesByKeys(['site-1/a', 'site-1/b', 'site-1/a']);

      expect(client.request).toHaveBeenCalledTimes(1);
      expect(requestedKeys(client, 0)).toEqual(['site-1/a', 'site-1/b']);
      expect(result.map((file) => file.key)).toEqual(['site-1/a', 'site-1/b']);
    });
  });
});
