import type { Drive } from '@microsoft/microsoft-graph-types';
import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphBatchService } from './graph-batch.service';
import { GraphClientFactory } from './graph-client.factory';
import type {
  BatchRequest,
  BatchResponsePayload,
  DriveItemsResponse,
} from './types/batch.types';

describe('GraphBatchService', () => {
  let service: GraphBatchService;
  let mockGraphClient: {
    api: ReturnType<typeof vi.fn>;
  };

  const mockBatchRequest: BatchRequest = {
    id: '1',
    method: 'GET',
    url: '/sites/site-1',
  };

  const mockBatchResponse: BatchResponsePayload = {
    responses: [
      {
        id: '1',
        status: 200,
        body: { webUrl: 'https://sharepoint.example.com/sites/site-1' },
      },
    ],
  };

  beforeEach(async () => {
    mockGraphClient = {
      api: vi.fn(),
    };

    const mockChain = {
      post: vi.fn(),
    };

    mockGraphClient.api.mockReturnValue(mockChain);
    mockChain.post.mockResolvedValue(mockBatchResponse);

    const { unit } = await TestBed.solitary(GraphBatchService)
      .mock(GraphClientFactory)
      .impl(() => ({
        createClient: () => mockGraphClient,
      }))
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint.graphRateLimitPer10Seconds') return 10000;
          return undefined;
        }),
      }))
      .compile();

    service = unit;

    // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
    (service as any).makeRateLimitedRequest = vi.fn().mockImplementation(
      // biome-ignore lint/suspicious/noExplicitAny: Generic promise type for mocking
      (requestFn: () => Promise<any>) => requestFn(),
    );
  });

  describe('executeBatch', () => {
    it('executes single batch request successfully', async () => {
      const results = await service.executeBatch([mockBatchRequest]);

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(true);
      expect(results[0].status).toBe(200);
      expect(mockGraphClient.api).toHaveBeenCalledWith('/$batch');
    });

    it('handles empty request array', async () => {
      const results = await service.executeBatch([]);

      expect(results).toHaveLength(0);
      expect(mockGraphClient.api).not.toHaveBeenCalled();
    });

    it('splits large batches into chunks', async () => {
      const largeRequests: BatchRequest[] = Array.from({ length: 25 }, (_, i) => ({
        id: `${i}`,
        method: 'GET',
        url: `/test/${i}`,
      }));

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: largeRequests.slice(0, 20).map((req) => ({
          id: req.id,
          status: 200,
          body: { data: `test-${req.id}` },
        })),
      });

      await service.executeBatch(largeRequests);

      expect(mockGraphClient.api).toHaveBeenCalledTimes(2);
    });

    it('handles failed batch requests', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.post.mockRejectedValue(new Error('Network error'));

      const results = await service.executeBatch([mockBatchRequest]);

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(false);
      expect(results[0].status).toBe(500);
      expect(results[0].error?.message).toContain('Network error');
    });

    it('handles individual request failures within batch', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: '1',
            status: 404,
            body: {
              error: {
                code: 'NotFound',
                message: 'Resource not found',
              },
            },
          },
        ],
      });

      const results = await service.executeBatch([mockBatchRequest]);

      expect(results).toHaveLength(1);
      expect(results[0].success).toBe(false);
      expect(results[0].status).toBe(404);
      expect(results[0].error?.code).toBe('NotFound');
    });
  });

  describe('fetchSiteMetadata', () => {
    it('fetches site metadata successfully', async () => {
      const mockDrives: Drive[] = [
        { id: 'drive-1', name: 'Documents' },
        { id: 'drive-2', name: 'Shared Documents' },
      ];

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: 'site',
            status: 200,
            body: { webUrl: 'https://sharepoint.example.com/sites/site-1' },
          },
          {
            id: 'drives',
            status: 200,
            body: { value: mockDrives },
          },
        ],
      });

      const result = await service.fetchSiteMetadata('site-1');

      expect(result.webUrl).toBe('https://sharepoint.example.com/sites/site-1');
      expect(result.drives).toHaveLength(2);
      expect(result.drives[0].name).toBe('Documents');
    });

    it('throws error when site metadata fetch fails', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: 'site',
            status: 404,
            body: {
              error: {
                code: 'NotFound',
                message: 'Site not found',
              },
            },
          },
          {
            id: 'drives',
            status: 200,
            body: { value: [] },
          },
        ],
      });

      await expect(service.fetchSiteMetadata('site-1')).rejects.toThrow('Failed to fetch site metadata');
    });

    it('handles empty drives list', async () => {
      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: 'site',
            status: 200,
            body: { webUrl: 'https://sharepoint.example.com/sites/site-1' },
          },
          {
            id: 'drives',
            status: 200,
            body: { value: [] },
          },
        ],
      });

      const result = await service.fetchSiteMetadata('site-1');

      expect(result.webUrl).toBe('https://sharepoint.example.com/sites/site-1');
      expect(result.drives).toHaveLength(0);
    });
  });

  describe('fetchMultipleFolderChildren', () => {
    it('fetches children for multiple folders successfully', async () => {
      const requests = [
        { driveId: 'drive-1', itemId: 'folder-1', selectFields: ['id', 'name'] },
        { driveId: 'drive-1', itemId: 'folder-2', selectFields: ['id', 'name'] },
      ];

      const mockItems: DriveItemsResponse[] = [
        {
          value: [
            { id: 'file-1', name: 'test1.pdf' },
            { id: 'file-2', name: 'test2.pdf' },
          ],
        },
        {
          value: [{ id: 'file-3', name: 'test3.pdf' }],
        },
      ];

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: '0',
            status: 200,
            body: mockItems[0],
          },
          {
            id: '1',
            status: 200,
            body: mockItems[1],
          },
        ],
      });

      const result = await service.fetchMultipleFolderChildren(requests);

      expect(result.size).toBe(2);
      expect(result.get('drive-1:folder-1')?.value).toHaveLength(2);
      expect(result.get('drive-1:folder-2')?.value).toHaveLength(1);
    });

    it('handles failed folder requests gracefully', async () => {
      const requests = [
        { driveId: 'drive-1', itemId: 'folder-1', selectFields: ['id', 'name'] },
        { driveId: 'drive-1', itemId: 'folder-2', selectFields: ['id', 'name'] },
      ];

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: '0',
            status: 200,
            body: { value: [{ id: 'file-1', name: 'test1.pdf' }] },
          },
          {
            id: '1',
            status: 404,
            body: {
              error: {
                code: 'NotFound',
                message: 'Folder not found',
              },
            },
          },
        ],
      });

      const result = await service.fetchMultipleFolderChildren(requests);

      expect(result.size).toBe(2);
      expect(result.get('drive-1:folder-1')?.value).toHaveLength(1);
      expect(result.get('drive-1:folder-2')?.value).toHaveLength(0);
    });

    it('handles empty folder results', async () => {
      const requests = [{ driveId: 'drive-1', itemId: 'folder-1', selectFields: ['id', 'name'] }];

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: [
          {
            id: '0',
            status: 200,
            body: { value: [] },
          },
        ],
      });

      const result = await service.fetchMultipleFolderChildren(requests);

      expect(result.size).toBe(1);
      expect(result.get('drive-1:folder-1')?.value).toHaveLength(0);
    });

    it('batches large folder requests correctly', async () => {
      const requests = Array.from({ length: 25 }, (_, i) => ({
        driveId: 'drive-1',
        itemId: `folder-${i}`,
        selectFields: ['id', 'name'],
      }));

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue({
        responses: Array.from({ length: 20 }, (_, i) => ({
          id: `${i}`,
          status: 200,
          body: { value: [{ id: `file-${i}`, name: `test-${i}.pdf` }] },
        })),
      });

      await service.fetchMultipleFolderChildren(requests);

      expect(mockGraphClient.api).toHaveBeenCalledTimes(2);
    });
  });

  describe('rate limiting', () => {
    it('respects rate limits when making batch requests', async () => {
      const { unit } = await TestBed.solitary(GraphBatchService)
        .mock(GraphClientFactory)
        .impl(() => ({
          createClient: () => mockGraphClient,
        }))
        .mock(ConfigService)
        .impl((stub) => ({
          ...stub(),
          get: vi.fn((key: string) => {
            if (key === 'sharepoint.graphRateLimitPer10Seconds') return 5;
            return undefined;
          }),
        }))
        .compile();

      const rateLimitedService = unit;

      const mockChain = mockGraphClient.api();
      mockChain.post.mockResolvedValue(mockBatchResponse);

      await rateLimitedService.executeBatch([mockBatchRequest]);

      expect(mockGraphClient.api).toHaveBeenCalled();
    });
  });
});

