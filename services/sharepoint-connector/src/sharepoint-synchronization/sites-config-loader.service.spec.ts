import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import type { SharepointConfig, SiteConfig } from '../config/sharepoint.schema';
import { IngestionMode } from '../constants/ingestion.constants';
import { StoreInternallyMode } from '../constants/store-internally-mode.enum';
import type { ListItem } from '../microsoft-apis/graph/types/sharepoint.types';
import { SitesConfigLoaderService } from './sites-config-loader.service';

describe('SitesConfigLoaderService', () => {
  describe('loadSites', () => {
    it('returns sites array for configFile source', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const mockSites: SiteConfig[] = [
        {
          siteId: '12345678-1234-4234-8234-123456789abc',
          syncColumnName: 'TestColumn',
          ingestionMode: IngestionMode.Flat,
          scopeId: 'scope_test',
          storeInternally: StoreInternallyMode.Enabled,
          syncStatus: 'active',
          syncMode: 'content_only',
        },
      ];

      const config: Partial<SharepointConfig> = {
        sitesSource: 'configFile',
        sites: mockSites,
      } as SharepointConfig;

      const result = await unit.loadSites(config as SharepointConfig);

      expect(result).toEqual(mockSites);
    });

    it('fetches sites from SharePoint list for sharePointList source', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const mockSiteConfig: SiteConfig = {
        siteId: '12345678-1234-4234-8234-123456789abc',
        syncColumnName: 'TestColumn',
        ingestionMode: IngestionMode.Recursive,
        scopeId: 'scope_test',
        maxFilesToIngest: 100,
        storeInternally: StoreInternallyMode.Enabled,
        syncStatus: 'active',
        syncMode: 'content_and_permissions',
      };

      // biome-ignore lint/suspicious/noExplicitAny: Mock private method for testing
      vi.spyOn(unit as any, 'fetchFromSharePointList').mockResolvedValue([mockSiteConfig]);

      const config = {
        sitesSource: 'sharePointList' as const,
        sharepointListUrl: 'https://test.sharepoint.com/sites/Test/Lists/TestList/AllItems.aspx',
      } as SharepointConfig;

      const result = await unit.loadSites(config);

      expect(result).toEqual([mockSiteConfig]);
      if (config.sitesSource === 'sharePointList') {
        // biome-ignore lint/suspicious/noExplicitAny: Check private method was called
        expect((unit as any).fetchFromSharePointList).toHaveBeenCalledWith(
          config.sharepointListUrl,
        );
      }
    });
  });

  describe('parseListUrl', () => {
    it('correctly parses SharePoint list URL', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const url =
        'https://uniqueapp.sharepoint.com/sites/QA/Lists/Sharepoint%20Sites%20to%20Sync/AllItems.aspx';

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = (unit as any).parseListUrl(url);

      expect(result).toEqual({
        hostname: 'uniqueapp.sharepoint.com',
        relativePath: '/sites/QA',
        listName: 'Sharepoint Sites to Sync',
      });
    });

    it('correctly parses URL with nested site path', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const url =
        'https://test.sharepoint.com/sites/Parent/SubSite/Lists/Config%20List/AllItems.aspx';

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = (unit as any).parseListUrl(url);

      expect(result).toEqual({
        hostname: 'test.sharepoint.com',
        relativePath: '/sites/Parent/SubSite',
        listName: 'Config List',
      });
    });

    it('throws error for invalid URL without Lists segment', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const url = 'https://test.sharepoint.com/sites/Test/SomeOtherPath';

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      expect(() => (unit as any).parseListUrl(url)).toThrow('Invalid SharePoint list URL');
    });

    it('throws error for malformed URL', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const url = 'not-a-valid-url';

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      expect(() => (unit as any).parseListUrl(url)).toThrow('Invalid SharePoint list URL');
    });
  });

  describe('transformListItemToSiteConfig', () => {
    it('correctly transforms valid list item to SiteConfig', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const listItem = {
        id: '1',
        fields: {
          syncSiteId: '12345678-1234-4234-8234-123456789abc',
          syncColumnName: 'TestColumn',
          ingestionMode: 'recursive',
          uniqueScopeId: 'scope_test',
          maxFilesToIngest: 100,
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_and_permissions',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = (unit as any).transformListItemToSiteConfig(listItem, 0);

      expect(result).toEqual({
        siteId: '12345678-1234-4234-8234-123456789abc',
        syncColumnName: 'TestColumn',
        ingestionMode: 'recursive',
        scopeId: 'scope_test',
        maxFilesToIngest: 100,
        storeInternally: 'enabled',
        syncStatus: 'active',
        syncMode: 'content_and_permissions',
      });
    });

    it('validates and rejects invalid siteId format', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const listItem = {
        id: '1',
        fields: {
          siteId: 'invalid-uuid',
          syncColumnName: 'TestColumn',
          ingestionMode: 'recursive',
          scopeId: 'scope_test',
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_only',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      expect(() => (unit as any).transformListItemToSiteConfig(listItem, 0)).toThrow(
        'Invalid site configuration at row 1',
      );
    });

    it('validates and rejects invalid ingestionMode', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const listItem = {
        id: '1',
        fields: {
          siteId: '12345678-1234-4234-8234-123456789abc',
          syncColumnName: 'TestColumn',
          ingestionMode: 'invalid-mode',
          scopeId: 'scope_test',
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_only',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      expect(() => (unit as any).transformListItemToSiteConfig(listItem, 0)).toThrow(
        'Invalid site configuration at row 1',
      );
    });

    it('validates and rejects invalid syncStatus', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const listItem = {
        id: '1',
        fields: {
          siteId: '12345678-1234-4234-8234-123456789abc',
          syncColumnName: 'TestColumn',
          ingestionMode: 'recursive',
          scopeId: 'scope_test',
          storeInternally: 'enabled',
          syncStatus: 'invalid-status',
          syncMode: 'content_only',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      expect(() => (unit as any).transformListItemToSiteConfig(listItem, 0)).toThrow(
        'Invalid site configuration at row 1',
      );
    });

    it('correctly handles optional maxFilesToIngest', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const listItem = {
        id: '1',
        fields: {
          syncSiteId: '12345678-1234-4234-8234-123456789abc',
          syncColumnName: 'TestColumn',
          ingestionMode: 'flat',
          uniqueScopeId: 'scope_test',
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_only',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = (unit as any).transformListItemToSiteConfig(listItem, 0);

      expect(result.maxFilesToIngest).toBeUndefined();
    });
  });

  describe('integration scenario - fetchFromSharePointList', () => {
    it('successfully fetches and transforms sites from SharePoint list', async () => {
      const { unit } = await TestBed.solitary(SitesConfigLoaderService).compile();

      const mockGraphClient = {
        api: vi.fn().mockReturnThis(),
        select: vi.fn().mockReturnThis(),
        filter: vi.fn().mockReturnThis(),
        expand: vi.fn().mockReturnThis(),
        top: vi.fn().mockReturnThis(),
        get: vi.fn(),
      };

      // Mock getSiteIdByUrl response
      mockGraphClient.get.mockResolvedValueOnce({
        id: 'site-id-123',
      });

      // Mock getListIdByName response
      mockGraphClient.get.mockResolvedValueOnce({
        value: [{ id: 'list-id-456', name: 'Test List', displayName: 'Test List' }],
      });

      // Mock getListItems response
      mockGraphClient.get.mockResolvedValueOnce({
        value: [
          {
            id: '1',
            fields: {
              syncSiteId: '12345678-1234-4234-8123-123456789abc',
              syncColumnName: 'TestColumn',
              ingestionMode: 'recursive',
              uniqueScopeId: 'scope_test',
              maxFilesToIngest: 100,
              storeInternally: 'enabled',
              syncStatus: 'active',
              syncMode: 'content_and_permissions',
            },
          },
        ],
      });

      // Replace the graphClient with our mock
      // biome-ignore lint/suspicious/noExplicitAny: Mock private property for testing
      (unit as any).graphClient = mockGraphClient;

      const url = 'https://test.sharepoint.com/sites/Test/Lists/Test%20List/AllItems.aspx';

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = await (unit as any).fetchFromSharePointList(url);

      expect(result).toHaveLength(1);
      expect(result[0]).toEqual({
        siteId: '12345678-1234-4234-8123-123456789abc',
        syncColumnName: 'TestColumn',
        ingestionMode: 'recursive',
        scopeId: 'scope_test',
        maxFilesToIngest: 100,
        storeInternally: 'enabled',
        syncStatus: 'active',
        syncMode: 'content_and_permissions',
      });

      expect(mockGraphClient.api).toHaveBeenCalledWith('/sites/test.sharepoint.com:/sites/Test');
    });
  });
});
