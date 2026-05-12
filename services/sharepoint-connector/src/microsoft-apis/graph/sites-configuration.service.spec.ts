import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { describe, expect, it, vi } from 'vitest';
import { PartialSiteConfigSchema, SiteDefaultsSchema } from '../../config/sharepoint.schema';
import { createSmeared, Smeared } from '../../utils/smeared';
import { GraphApiService } from './graph-api.service';
import { SitesConfigurationService } from './sites-configuration.service';
import type { ListColumn, ListItem } from './types/sharepoint.types';

const SITE_UUID = '12345678-1234-4234-8123-123456789abc';
const SECOND_SITE_UUID = '87654321-4321-4321-8321-cba987654321';

const SHAREPOINT_LIST_COLUMNS: ListColumn[] = [
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
  { id: 'c10', name: 'internal_subsitesScan', displayName: 'subsitesScan' },
];

interface MockGraphApiService {
  getListItems: ReturnType<typeof vi.fn>;
  getListColumns: ReturnType<typeof vi.fn>;
}

async function setupService(sharepointConfig: unknown): Promise<{
  service: SitesConfigurationService;
  graphApi: MockGraphApiService;
}> {
  const graphApi: MockGraphApiService = {
    getListItems: vi.fn(),
    getListColumns: vi.fn(),
  };

  const { unit } = await TestBed.solitary(SitesConfigurationService)
    .mock(GraphApiService)
    .impl(() => graphApi)
    .mock(ConfigService)
    .impl((stub) => ({
      ...stub(),
      get: vi.fn((key: string) => (key === 'sharepoint' ? sharepointConfig : undefined)),
    }))
    .compile();

  return { service: unit, graphApi };
}

describe('SitesConfigurationService', () => {
  describe('loadSitesConfiguration', () => {
    describe('config_file mode', () => {
      it('loads sites from config file with all per-site values', async () => {
        const { service } = await setupService({
          sitesSource: 'config_file',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sites: [
            PartialSiteConfigSchema.parse({
              siteId: SITE_UUID,
              syncColumnName: 'TestColumn',
              ingestionMode: 'recursive',
              scopeId: 'scope_test',
              maxFilesToIngest: 100,
              storeInternally: 'enabled',
              syncStatus: 'active',
              syncMode: 'content_and_permissions',
              permissionsInheritanceMode: 'inherit_scopes_and_files',
              subsitesScan: 'disabled',
            }),
          ],
        });

        const [site, ...rest] = await service.loadSitesConfiguration();
        if (!site) {
          throw new Error('expected one site');
        }

        expect(rest).toHaveLength(0);
        expect(site.siteId).toBeInstanceOf(Smeared);
        expect(site.siteId.value).toBe(SITE_UUID);
        expect(site).toMatchObject({
          syncColumnName: 'TestColumn',
          ingestionMode: 'recursive',
          scopeId: { type: 'fixed', scopeId: 'scope_test' },
          maxFilesToIngest: 100,
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_and_permissions',
          permissionsInheritanceMode: 'inherit_scopes_and_files',
          subsitesScan: 'disabled',
        });
      });

      it('merges siteDefaults into rows that omit fields', async () => {
        const { service } = await setupService({
          sitesSource: 'config_file',
          siteDefaults: SiteDefaultsSchema.parse({
            syncColumnName: 'DefaultColumn',
            ingestionMode: 'flat',
            scopeId: 'scope_default',
            syncMode: 'content_only',
            subsitesScan: 'enabled',
          }),
          sites: [
            PartialSiteConfigSchema.parse({
              siteId: SITE_UUID,
              scopeId: 'scope_override',
            }),
          ],
        });

        const result = await service.loadSitesConfiguration();

        expect(result).toHaveLength(1);
        expect(result[0]).toMatchObject({
          syncColumnName: 'DefaultColumn',
          ingestionMode: 'flat',
          scopeId: { type: 'fixed', scopeId: 'scope_override' },
          syncMode: 'content_only',
          subsitesScan: 'enabled',
          // schema-level defaults from SiteDefaultsSchema.parse({...}) propagate too
          storeInternally: 'enabled',
          syncStatus: 'active',
          permissionsInheritanceMode: 'inherit_scopes_and_files',
        });
      });

      it('applies schema-level defaults when siteDefaults is empty and per-site has all required fields', async () => {
        const { service } = await setupService({
          sitesSource: 'config_file',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sites: [
            PartialSiteConfigSchema.parse({
              siteId: SITE_UUID,
              ingestionMode: 'recursive',
              scopeId: 'scope_required',
              syncMode: 'content_and_permissions',
            }),
          ],
        });

        const result = await service.loadSitesConfiguration();

        expect(result).toHaveLength(1);
        expect(result[0]).toMatchObject({
          syncColumnName: 'FinanceGPTKnowledge',
          ingestionMode: 'recursive',
          scopeId: { type: 'fixed', scopeId: 'scope_required' },
          syncMode: 'content_and_permissions',
          storeInternally: 'enabled',
          syncStatus: 'active',
          permissionsInheritanceMode: 'inherit_scopes_and_files',
          subsitesScan: 'disabled',
        });
      });

      it('throws when a row is missing a required field with no default', async () => {
        const { service } = await setupService({
          sitesSource: 'config_file',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sites: [
            PartialSiteConfigSchema.parse({
              siteId: SITE_UUID,
              ingestionMode: 'recursive',
              scopeId: 'scope_first',
              syncMode: 'content_and_permissions',
            }),
            PartialSiteConfigSchema.parse({
              siteId: SECOND_SITE_UUID,
              ingestionMode: 'recursive',
              syncMode: 'content_and_permissions',
              // scopeId omitted, no default
            }),
          ],
        });

        await expect(service.loadSitesConfiguration()).rejects.toThrow(
          /config_file row 2.*scopeId/,
        );
      });
    });

    describe('sharepoint_list mode', () => {
      it('fetches and transforms sites from SharePoint list', async () => {
        const { service, graphApi } = await setupService({
          sitesSource: 'sharepoint_list',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sharepointList: {
            siteId: createSmeared('test-site-id'),
            listId: 'list-id-456',
          },
        });

        graphApi.getListColumns.mockResolvedValue(SHAREPOINT_LIST_COLUMNS);
        graphApi.getListItems.mockResolvedValue([
          {
            id: '1',
            fields: {
              internal_siteId: SITE_UUID,
              internal_syncColumnName: 'TestColumn',
              internal_ingestionMode: 'recursive',
              internal_uniqueScopeId: 'scope_test',
              internal_maxFilesToIngest: 100,
              internal_storeInternally: 'enabled',
              internal_syncStatus: 'active',
              internal_syncMode: 'content_and_permissions',
              internal_permissionsInheritanceMode: 'inherit_scopes_and_files',
              internal_subsitesScan: 'disabled',
            },
          } as unknown as ListItem,
        ]);

        const [site, ...rest] = await service.loadSitesConfiguration();
        if (!site) {
          throw new Error('expected one site');
        }

        expect(rest).toHaveLength(0);
        expect(site.siteId).toBeInstanceOf(Smeared);
        expect(site.siteId.value).toBe(SITE_UUID);
        expect(site).toMatchObject({
          syncColumnName: 'TestColumn',
          ingestionMode: 'recursive',
          scopeId: { type: 'fixed', scopeId: 'scope_test' },
          maxFilesToIngest: 100,
          storeInternally: 'enabled',
          syncStatus: 'active',
          syncMode: 'content_and_permissions',
          permissionsInheritanceMode: 'inherit_scopes_and_files',
          subsitesScan: 'disabled',
        });

        expect(graphApi.getListItems).toHaveBeenCalledWith(expect.any(Smeared), 'list-id-456', {
          expand: 'fields',
        });
        expect(graphApi.getListColumns).toHaveBeenCalledWith(expect.any(Smeared), 'list-id-456');
      });

      it('merges siteDefaults into rows fetched from Graph that omit fields', async () => {
        const { service, graphApi } = await setupService({
          sitesSource: 'sharepoint_list',
          siteDefaults: SiteDefaultsSchema.parse({
            syncColumnName: 'DefaultColumn',
            ingestionMode: 'flat',
            scopeId: 'scope_default',
            syncMode: 'content_only',
            subsitesScan: 'enabled',
          }),
          sharepointList: {
            siteId: createSmeared('test-site-id'),
            listId: 'list-id-456',
          },
        });

        graphApi.getListColumns.mockResolvedValue(SHAREPOINT_LIST_COLUMNS);
        graphApi.getListItems.mockResolvedValue([
          {
            id: '1',
            fields: {
              internal_siteId: SITE_UUID,
              internal_uniqueScopeId: 'scope_override',
              // sharepoint sets unset numeric cells to 0; transformer maps that to undefined
              internal_maxFilesToIngest: 0,
            },
          } as unknown as ListItem,
        ]);

        const [site, ...rest] = await service.loadSitesConfiguration();
        if (!site) {
          throw new Error('expected one site');
        }

        expect(rest).toHaveLength(0);
        expect(site).toMatchObject({
          syncColumnName: 'DefaultColumn',
          ingestionMode: 'flat',
          scopeId: { type: 'fixed', scopeId: 'scope_override' },
          syncMode: 'content_only',
          subsitesScan: 'enabled',
          storeInternally: 'enabled',
          syncStatus: 'active',
          permissionsInheritanceMode: 'inherit_scopes_and_files',
        });
        expect(site.maxFilesToIngest).toBeUndefined();
      });

      it('throws when a SharePoint list row is missing a required field with no default', async () => {
        const { service, graphApi } = await setupService({
          sitesSource: 'sharepoint_list',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sharepointList: {
            siteId: createSmeared('test-site-id'),
            listId: 'list-id-456',
          },
        });

        graphApi.getListColumns.mockResolvedValue(SHAREPOINT_LIST_COLUMNS);
        graphApi.getListItems.mockResolvedValue([
          {
            id: '1',
            fields: {
              internal_siteId: SITE_UUID,
              internal_ingestionMode: 'recursive',
              internal_uniqueScopeId: 'scope_first',
              internal_syncMode: 'content_and_permissions',
            },
          } as unknown as ListItem,
          {
            id: '2',
            fields: {
              internal_siteId: SECOND_SITE_UUID,
              internal_ingestionMode: 'recursive',
              // uniqueScopeId omitted, no default
              internal_syncMode: 'content_and_permissions',
            },
          } as unknown as ListItem,
        ]);

        await expect(service.loadSitesConfiguration()).rejects.toThrow(
          /sharepoint_list row 2.*scopeId/,
        );
      });

      it('rejects rows with invalid siteId format', async () => {
        const { service, graphApi } = await setupService({
          sitesSource: 'sharepoint_list',
          siteDefaults: SiteDefaultsSchema.parse({}),
          sharepointList: {
            siteId: createSmeared('test-site-id'),
            listId: 'list-id-456',
          },
        });

        graphApi.getListColumns.mockResolvedValue(SHAREPOINT_LIST_COLUMNS);
        graphApi.getListItems.mockResolvedValue([
          {
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
          } as unknown as ListItem,
        ]);

        await expect(service.loadSitesConfiguration()).rejects.toThrow(
          /Invalid site configuration at row 1/,
        );
      });
    });
  });
});
