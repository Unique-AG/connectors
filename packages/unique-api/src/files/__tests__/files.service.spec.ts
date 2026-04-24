import { describe, expect, it, vi } from 'vitest';
import type { UniqueGraphqlClient } from '../../clients/unique-graphql.client';
import { type ContentByScopeResult, PAGINATED_CONTENT_IDS_QUERY } from '../files.queries';
import { FilesService } from '../files.service';

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

function createBatchResponse(ids: string[]): ContentByScopeResult {
  return {
    paginatedContent: {
      nodes: ids.map((id) => ({ id })),
      totalCount: ids.length,
    },
  };
}

describe('FilesService', () => {
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
});
