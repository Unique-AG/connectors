import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphApiService } from './graph-api.service';
import { SitesConfigurationService } from './sites-configuration.service';
import type { ListColumn, ListItem } from './types/sharepoint.types';

describe('SitesConfigurationService', () => {
  let service: SitesConfigurationService;
  let mockGraphApiService: {
    getListItems: ReturnType<typeof vi.fn>;
    getListColumns: ReturnType<typeof vi.fn>;
  };

  beforeEach(async () => {
    mockGraphApiService = {
      getListItems: vi.fn(),
      getListColumns: vi.fn(),
    };

    const { unit } = await TestBed.solitary(SitesConfigurationService)
      .mock(GraphApiService)
      .impl(() => mockGraphApiService)
      .mock(ConfigService)
      .impl((stub) => ({
        ...stub(),
        get: vi.fn((key: string) => {
          if (key === 'sharepoint') {
            return {
              sitesSource: 'config_file',
              sites: [
                {
                  siteId: '12345678-1234-4234-8123-123456789abc',
                  syncColumnName: 'TestColumn',
                  ingestionMode: 'recursive',
                  scopeId: 'scope_test',
                  maxFilesToIngest: 100,
                  storeInternally: 'enabled',
                  syncStatus: 'active',
                  syncMode: 'content_and_permissions',
                  permissionsInheritanceMode: 'inherit_scopes_and_files',
                },
              ],
            };
          }
          return undefined;
        }),
      }))
      .compile();

    service = unit;
  });

  describe('loadSitesConfiguration', () => {
    it('loads sites from config file when sitesSource is config_file', async () => {
      const result = await service.loadSitesConfiguration();

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
        permissionsInheritanceMode: 'inherit_scopes_and_files',
      });
    });
  });

  describe('fetchSitesFromSharePointList', () => {
    it('successfully fetches and transforms sites from SharePoint list', async () => {
      const mockColumns: ListColumn[] = [
        { id: 'c1', name: 'internal_siteId', displayName: 'siteId' },
        { id: 'c2', name: 'internal_syncColumnName', displayName: 'syncColumnName' },
        { id: 'c3', name: 'internal_ingestionMode', displayName: 'ingestionMode' },
        { id: 'c4', name: 'internal_uniqueScopeId', displayName: 'uniqueScopeId' },
        { id: 'c5', name: 'internal_maxFilesToIngest', displayName: 'maxFilesToIngest' },
        { id: 'c6', name: 'internal_storeInternally', displayName: 'storeInternally' },
        { id: 'c7', name: 'internal_syncStatus', displayName: 'syncStatus' },
        { id: 'c8', name: 'internal_syncMode', displayName: 'syncMode' },
        {
          id: 'c9',
          name: 'internal_permissionsInheritanceMode',
          displayName: 'permissionsInheritanceMode',
        },
      ];

      mockGraphApiService.getListColumns.mockResolvedValue(mockColumns);

      const mockListItem = {
        id: '1',
        fields: {
          internal_siteId: '12345678-1234-4234-8123-123456789abc',
          internal_syncColumnName: 'TestColumn',
          internal_ingestionMode: 'recursive',
          internal_uniqueScopeId: 'scope_test',
          internal_maxFilesToIngest: 100,
          internal_storeInternally: 'enabled',
          internal_syncStatus: 'active',
          internal_syncMode: 'content_and_permissions',
          internal_permissionsInheritanceMode: 'inherit_scopes_and_files',
        },
      };

      mockGraphApiService.getListItems.mockResolvedValue([mockListItem as unknown as ListItem]);

      const sharepointList = {
        siteId: 'test-site-id',
        listId: 'list-id-456',
      };

      const result = await service.fetchSitesFromSharePointList(sharepointList);

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
        permissionsInheritanceMode: 'inherit_scopes_and_files',
      });

      expect(mockGraphApiService.getListItems).toHaveBeenCalledWith('test-site-id', 'list-id-456', {
        expand: 'fields',
      });
      expect(mockGraphApiService.getListColumns).toHaveBeenCalledWith(
        'test-site-id',
        'list-id-456',
      );
    });
  });

  describe('transformListItemToSiteConfig', () => {
    const mockNameMap = {
      siteId: 'internal_siteId',
      syncColumnName: 'internal_syncColumnName',
      ingestionMode: 'internal_ingestionMode',
      uniqueScopeId: 'internal_uniqueScopeId',
      maxFilesToIngest: 'internal_maxFilesToIngest',
      storeInternally: 'internal_storeInternally',
      syncStatus: 'internal_syncStatus',
      syncMode: 'internal_syncMode',
      permissionsInheritanceMode: 'internal_permissionsInheritanceMode',
    };

    it('correctly transforms valid list item to SiteConfig', () => {
      const listItem = {
        id: '1',
        fields: {
          internal_siteId: '12345678-1234-4234-8234-123456789abc',
          internal_syncColumnName: 'TestColumn',
          internal_ingestionMode: 'recursive',
          internal_uniqueScopeId: 'scope_test',
          internal_maxFilesToIngest: 100,
          internal_storeInternally: 'enabled',
          internal_syncStatus: 'active',
          internal_syncMode: 'content_and_permissions',
          internal_permissionsInheritanceMode: 'inherit_scopes_and_files',
        },
      } as unknown as ListItem;

      // biome-ignore lint/suspicious/noExplicitAny: Test private method
      const result = (service as any).transformListItemToSiteConfig(listItem, 0, mockNameMap);

      expect(result).toEqual({
        siteId: '12345678-1234-4234-8234-123456789abc',
        syncColumnName: 'TestColumn',
        ingestionMode: 'recursive',
        scopeId: 'scope_test',
        maxFilesToIngest: 100,
        storeInternally: 'enabled',
        syncStatus: 'active',
        syncMode: 'content_and_permissions',
        permissionsInheritanceMode: 'inherit_scopes_and_files',
      });
    });

    it('validates and rejects invalid siteId format', () => {
      const listItem = {
        id: '1',
        fields: {
          internal_siteId: 'invalid-uuid',
          internal_syncColumnName: 'TestColumn',
          internal_ingestionMode: 'recursive',
          internal_uniqueScopeId: 'scope_test',
          internal_storeInternally: 'enabled',
          internal_syncStatus: 'active',
          internal_syncMode: 'content_only',
        },
      } as unknown as ListItem;

      expect(() =>
        // biome-ignore lint/suspicious/noExplicitAny: Test private method
        (service as any).transformListItemToSiteConfig(listItem, 0, mockNameMap),
      ).toThrow('Invalid site configuration at row 1');
    });
  });
});
