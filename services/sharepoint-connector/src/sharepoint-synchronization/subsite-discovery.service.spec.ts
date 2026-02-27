import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { Smeared } from '../utils/smeared';
import { SubsiteDiscoveryService } from './subsite-discovery.service';

describe('SubsiteDiscoveryService', () => {
  let service: SubsiteDiscoveryService;
  let mockGraphApiService: { getSubsites: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    mockGraphApiService = {
      getSubsites: vi.fn().mockResolvedValue([]),
    };

    const { unit } = await TestBed.solitary(SubsiteDiscoveryService)
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .compile();

    service = unit;
  });

  describe('discoverAllSubsites', () => {
    const rootSiteId = new Smeared('root-site', false);

    it('returns empty array when no subsites exist', async () => {
      const result = await service.discoverAllSubsites(rootSiteId);

      expect(result).toEqual([]);
      expect(mockGraphApiService.getSubsites).toHaveBeenCalledOnce();
      expect(mockGraphApiService.getSubsites).toHaveBeenCalledWith(rootSiteId);
    });

    it('returns single-level subsites with name as relativePath', async () => {
      mockGraphApiService.getSubsites.mockImplementation((siteId: Smeared) => {
        if (siteId.value === 'root-site') {
          return Promise.resolve([
            {
              id: 'host,col,sub-b',
              name: 'B',
              displayName: 'Subsite B',
              webUrl: 'https://example.sharepoint.com/sites/root/B',
            },
            {
              id: 'host,col,sub-c',
              name: 'C',
              displayName: 'Subsite C',
              webUrl: 'https://example.sharepoint.com/sites/root/C',
            },
          ]);
        }
        return Promise.resolve([]);
      });

      const result = await service.discoverAllSubsites(rootSiteId);

      expect(result).toEqual([
        {
          siteId: expect.objectContaining({ value: 'host,col,sub-b' }),
          name: expect.objectContaining({ value: 'B' }),
          relativePath: expect.objectContaining({ value: 'B' }),
        },
        {
          siteId: expect.objectContaining({ value: 'host,col,sub-c' }),
          name: expect.objectContaining({ value: 'C' }),
          relativePath: expect.objectContaining({ value: 'C' }),
        },
      ]);
    });

    it('returns deeply nested subsites with full relative paths', async () => {
      mockGraphApiService.getSubsites.mockImplementation((siteId: Smeared) => {
        if (siteId.value === 'root-site') {
          return Promise.resolve([
            {
              id: 'host,col,sub-b',
              name: 'B',
              displayName: 'Subsite B',
              webUrl: 'https://example.sharepoint.com/sites/root/B',
            },
            {
              id: 'host,col,sub-c',
              name: 'C',
              displayName: 'Subsite C',
              webUrl: 'https://example.sharepoint.com/sites/root/C',
            },
          ]);
        }
        if (siteId.value === 'host,col,sub-b') {
          return Promise.resolve([
            {
              id: 'host,col,sub-d',
              name: 'D',
              displayName: 'Subsite D',
              webUrl: 'https://example.sharepoint.com/sites/root/B/D',
            },
          ]);
        }
        return Promise.resolve([]);
      });

      const result = await service.discoverAllSubsites(rootSiteId);

      expect(result).toEqual([
        {
          siteId: expect.objectContaining({ value: 'host,col,sub-b' }),
          name: expect.objectContaining({ value: 'B' }),
          relativePath: expect.objectContaining({ value: 'B' }),
        },
        {
          siteId: expect.objectContaining({ value: 'host,col,sub-d' }),
          name: expect.objectContaining({ value: 'D' }),
          relativePath: expect.objectContaining({ value: 'B/D' }),
        },
        {
          siteId: expect.objectContaining({ value: 'host,col,sub-c' }),
          name: expect.objectContaining({ value: 'C' }),
          relativePath: expect.objectContaining({ value: 'C' }),
        },
      ]);
      expect(mockGraphApiService.getSubsites).toHaveBeenCalledTimes(4);
    });

    it('propagates errors from getSubsites', async () => {
      const error = new Error('Graph API failure');
      mockGraphApiService.getSubsites.mockRejectedValue(error);

      await expect(service.discoverAllSubsites(rootSiteId)).rejects.toThrow('Graph API failure');
    });

    it('propagates errors from nested subsite discovery', async () => {
      mockGraphApiService.getSubsites.mockImplementation((siteId: Smeared) => {
        if (siteId.value === 'root-site') {
          return Promise.resolve([
            {
              id: 'host,col,sub-b',
              name: 'B',
              displayName: 'Subsite B',
              webUrl: 'https://example.sharepoint.com/sites/root/B',
            },
          ]);
        }
        return Promise.reject(new Error('Nested discovery failed'));
      });

      await expect(service.discoverAllSubsites(rootSiteId)).rejects.toThrow(
        'Nested discovery failed',
      );
    });
  });
});
