import { TestBed } from '@suites/unit';
import { TraceService } from 'nestjs-otel';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UniqueContentService } from '../services/unique-content.service';
import { UNIQUE_PUBLIC_FETCH, UNIQUE_PUBLIC_SDK_OPTIONS } from '../unique-public-sdk.consts';
import { SearchType } from '../unique-public-sdk.dtos';
import type { UniqueIdentity } from '../unique-public-sdk.types';

const context = describe;

const DEFAULT_OPTIONS = {
  apiBaseUrl: 'https://api.unique.app',
  apiVersion: '2023-12-06',
  serviceHeaders: {},
  retry: { maxAttempts: 3, baseDelayMs: 200, maxDelayMs: 10_000 },
};

const VALID_CONTENT_RESULT = {
  id: '1',
  key: 'test',
  url: null,
  title: 'Test',
  description: null,
  mimeType: 'text/plain',
  metadata: null,
  readUrl: 'https://read',
  writeUrl: 'https://write',
  object: 'content' as const,
};

const VALID_SEARCH_RESULT = {
  object: 'list' as const,
  data: [
    {
      object: 'search.search' as const,
      id: '1',
      chunkId: 'c1',
      text: 'hello',
      url: null,
      title: 'Test',
      key: 'k1',
      metadata: null,
      order: 0,
      startPage: 0,
      endPage: 0,
      internallyStoredAt: null,
      createdAt: '2024-01-01T00:00:00Z',
      updatedAt: '2024-01-01T00:00:00Z',
    },
  ],
};

const EMPTY_CONTENT_INFOS = {
  contentInfos: [],
  totalCount: 0,
  object: 'content-infos' as const,
};

describe('UniqueContentService', () => {
  let service: UniqueContentService;
  let mockFetch: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    mockFetch = vi.fn();
    const { unit } = await TestBed.solitary(UniqueContentService)
      .mock(UNIQUE_PUBLIC_FETCH)
      .impl(() => mockFetch)
      .mock(UNIQUE_PUBLIC_SDK_OPTIONS)
      .impl(() => DEFAULT_OPTIONS)
      .mock(TraceService)
      .impl(() => ({ getSpan: () => null }))
      .compile();
    service = unit;
  });

  describe('upsertContent', () => {
    context('when the API returns a valid content result', () => {
      beforeEach(() => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => VALID_CONTENT_RESULT });
      });

      it('returns the parsed content upsert result', async () => {
        const result = await service.upsertContent({
          input: { key: 'test', title: 'Test', mimeType: 'text/plain' },
          storeInternally: true,
        });

        expect(result).toEqual(VALID_CONTENT_RESULT);
      });

      it('sends a POST to content/upsert with JSON payload', async () => {
        await service.upsertContent({
          input: { key: 'test', title: 'Test', mimeType: 'text/plain' },
          storeInternally: true,
        });

        expect(mockFetch).toHaveBeenCalledWith(
          'content/upsert',
          expect.objectContaining({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
          }),
        );
      });
    });

    context('when the API returns invalid data', () => {
      it('throws a Zod validation error', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => ({ invalid: 'data' }) });

        await expect(
          service.upsertContent({
            input: { key: 'test', title: 'Test', mimeType: 'text/plain' },
            storeInternally: true,
          }),
        ).rejects.toThrow();
      });
    });

    context('when the fetch call fails', () => {
      it('propagates the error', async () => {
        mockFetch.mockRejectedValue(new Error('Network error'));

        await expect(
          service.upsertContent({
            input: { key: 'test', title: 'Test', mimeType: 'text/plain' },
            storeInternally: true,
          }),
        ).rejects.toThrow('Network error');
      });
    });
  });

  describe('uploadToStorage', () => {
    const originalFetch = globalThis.fetch;

    function createUploadService(storageInternalBaseUrl?: string) {
      return TestBed.solitary(UniqueContentService)
        .mock(UNIQUE_PUBLIC_FETCH)
        .impl(() => vi.fn())
        .mock(UNIQUE_PUBLIC_SDK_OPTIONS)
        .impl(() => ({ ...DEFAULT_OPTIONS, storageInternalBaseUrl }))
        .mock(TraceService)
        .impl(() => ({ getSpan: () => null }))
        .compile();
    }

    beforeEach(() => {
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: true });
    });

    afterEach(() => {
      globalThis.fetch = originalFetch;
    });

    context('when storageInternalBaseUrl is not configured', () => {
      it('uploads to the original writeUrl', async () => {
        const writeUrl = 'https://storage.blob.core.windows.net/container/blob?sv=2021';
        const { unit: svc } = await createUploadService(undefined);

        await svc.uploadToStorage(writeUrl, new ReadableStream(), 'text/plain');

        expect(globalThis.fetch).toHaveBeenCalledWith(
          writeUrl,
          expect.objectContaining({ method: 'PUT' }),
        );
      });

      it('sets Content-Type and x-ms-blob-type headers', async () => {
        const { unit: svc } = await createUploadService(undefined);

        await svc.uploadToStorage(
          'https://storage.blob.core.windows.net/blob',
          new ReadableStream(),
          'application/pdf',
        );

        expect(globalThis.fetch).toHaveBeenCalledWith(
          expect.any(String),
          expect.objectContaining({
            headers: {
              'Content-Type': 'application/pdf',
              'x-ms-blob-type': 'BlockBlob',
            },
          }),
        );
      });
    });

    context('when the storage endpoint returns a non-2xx status', () => {
      it('throws an error with the status code', async () => {
        globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, status: 403 });
        const { unit: svc } = await createUploadService(undefined);

        await expect(
          svc.uploadToStorage(
            'https://storage.blob.core.windows.net/blob',
            new ReadableStream(),
            'text/plain',
          ),
        ).rejects.toThrow('Unique storage upload failed: 403');
      });
    });
  });

  describe('getContentInfos', () => {
    context('when called with skip and take', () => {
      it('returns transformed result with contents and total', async () => {
        mockFetch.mockResolvedValue({
          ok: true,
          json: async () => ({
            contentInfos: [{ id: '1', key: 'k1', title: 'T1', mimeType: 'text/plain' }],
            totalCount: 1,
            object: 'content-infos' as const,
          }),
        });

        const result = await service.getContentInfos({ skip: 0, take: 10 });

        expect(result.contents).toHaveLength(1);
        expect(result.total).toBe(1);
      });

      it('sends correct pagination parameters', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => EMPTY_CONTENT_INFOS });

        await service.getContentInfos({ skip: 5, take: 25 });

        expect(mockFetch).toHaveBeenCalledWith(
          'content/infos',
          expect.objectContaining({
            method: 'POST',
            body: expect.stringContaining('"skip":5'),
          }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'content/infos',
          expect.objectContaining({ body: expect.stringContaining('"take":25') }),
        );
      });
    });

    context('when called with a metadata filter', () => {
      it('includes the filter in the request body', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => EMPTY_CONTENT_INFOS });

        await service.getContentInfos({
          skip: 0,
          take: 10,
          metadataFilter: { path: ['key'], operator: 'equals' as const, value: 'val' },
        });

        expect(mockFetch).toHaveBeenCalledWith(
          'content/infos',
          expect.objectContaining({ body: expect.stringContaining('"metadataFilter"') }),
        );
      });
    });
  });

  describe('findByMetadata', () => {
    const filter = { path: ['key'], operator: 'equals' as const, value: 'val' };

    context('when contents match the filter', () => {
      it('returns the matched contents with total count', async () => {
        mockFetch.mockResolvedValue({
          ok: true,
          json: async () => ({
            contentInfos: [{ id: '1', key: 'k1', title: 'T1', mimeType: 'text/plain' }],
            totalCount: 1,
            object: 'content-infos' as const,
          }),
        });

        const result = await service.findByMetadata(filter);

        expect(result.contents).toHaveLength(1);
        expect(result.total).toBe(1);
      });
    });

    context('when no contents match', () => {
      it('returns an empty array with total 0', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => EMPTY_CONTENT_INFOS });

        const result = await service.findByMetadata(filter);

        expect(result.contents).toEqual([]);
        expect(result.total).toBe(0);
      });
    });
  });

  describe('search', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => VALID_SEARCH_RESULT });
    });

    context('when called without scope context', () => {
      it('sends the search request without identity headers', async () => {
        await service.search({ searchString: 'test', searchType: SearchType.VECTOR });

        expect(mockFetch).not.toHaveBeenCalledWith(
          expect.anything(),
          expect.objectContaining({
            headers: expect.objectContaining({ 'x-user-id': expect.anything() }),
          }),
        );
      });
    });

    context('when called with scope context', () => {
      it('includes x-user-id and x-company-id headers', async () => {
        const identity: UniqueIdentity = { userId: 'u1', companyId: 'c1' };

        await service.search({ searchString: 'test', searchType: SearchType.VECTOR }, identity);

        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({
            headers: expect.objectContaining({ 'x-user-id': 'u1', 'x-company-id': 'c1' }),
          }),
        );
      });
    });

    context('when the API returns search results', () => {
      it('parses and returns the result', async () => {
        const result = await service.search({
          searchString: 'test',
          searchType: SearchType.VECTOR,
        });

        expect(result.data).toHaveLength(1);
        expect(result.object).toBe('list');
      });
    });
  });

  describe('scopedSearch', () => {
    context('when called with identity', () => {
      it('delegates to search with the identity', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => VALID_SEARCH_RESULT });
        const identity: UniqueIdentity = { userId: 'u1', companyId: 'c1' };

        const result = await service.scopedSearch(
          { searchString: 'test', searchType: SearchType.VECTOR },
          identity,
        );

        expect(result.data).toHaveLength(1);
        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({
            headers: expect.objectContaining({ 'x-user-id': 'u1' }),
          }),
        );
      });
    });
  });

  describe('searchByScope', () => {
    context('when searching with scope IDs', () => {
      it('creates a VECTOR search request with the given scope IDs and returns the data array', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => VALID_SEARCH_RESULT });

        const result = await service.searchByScope('test', ['scope1', 'scope2']);

        expect(result).toHaveLength(1);
        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({ body: expect.stringContaining('"searchType":"VECTOR"') }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({ body: expect.stringContaining('"scope1"') }),
        );
      });
    });
  });

  describe('searchByContent', () => {
    context('when searching with content IDs', () => {
      it('creates a VECTOR search request with the given content IDs and returns the data array', async () => {
        mockFetch.mockResolvedValue({ ok: true, json: async () => VALID_SEARCH_RESULT });

        const result = await service.searchByContent('test', ['content1', 'content2']);

        expect(result).toHaveLength(1);
        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({ body: expect.stringContaining('"searchType":"VECTOR"') }),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          'search/search',
          expect.objectContaining({ body: expect.stringContaining('"content1"') }),
        );
      });
    });
  });
});
