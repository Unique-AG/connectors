import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueApiService } from '../unique-api/unique-api.service';
import type { Scope } from '../unique-api/unique-api.types';
import { UniqueAuthService } from '../unique-api/unique-auth.service';
import { ScopeManagementService, type ScopePathToIdMap } from './scope-management.service';

const createDriveContentItem = (path: string): SharepointContentItem => {
  const webUrl = `https://example.sharepoint.com/sites/test1/${path}/Page%201.aspx`;

  return {
    itemType: 'driveItem',
    item: {
      '@odata.etag': 'etag-1',
      id: `drive-item-${path}`,
      name: 'Page 1.aspx',
      webUrl,
      size: 1024,
      lastModifiedDateTime: '2025-01-01T00:00:00Z',
      parentReference: {
        driveType: 'documentLibrary',
        driveId: 'drive-1',
        id: 'parent-id',
        name: 'Documents',
        path: `/drive/root:/${path}`,
        siteId: 'site-123',
      },
      file: {
        mimeType: 'text/html',
        hashes: {
          quickXorHash: 'hash-1',
        },
      },
      listItem: {
        '@odata.etag': 'etag-2',
        id: `list-item-${path}`,
        eTag: 'etag-2',
        createdDateTime: '2025-01-01T00:00:00Z',
        lastModifiedDateTime: '2025-01-01T00:00:00Z',
        webUrl,
        fields: {
          '@odata.etag': 'etag-2',
          FinanceGPTKnowledge: true,
          FileLeafRef: 'Page 1.aspx',
          Modified: '2025-01-01T00:00:00Z',
          Created: '2025-01-01T00:00:00Z',
          ContentType: 'Document',
          AuthorLookupId: '1',
          EditorLookupId: '1',
          ItemChildCount: '0',
          FolderChildCount: '0',
        },
      },
    },
    siteId: 'site-123',
    siteWebUrl: 'https://example.sharepoint.com/sites/test1',
    driveId: 'drive-1',
    driveName: 'Documents',
    folderPath: `/${path}`,
    fileName: 'Page 1.aspx',
  };
};

describe('ScopeManagementService', () => {
  const mockScopes: Scope[] = [
    { id: 'scope_1', name: '/test1' },
    { id: 'scope_2', name: '/test1/UniqueAG' },
    { id: 'scope_3', name: '/test1/UniqueAG/SitePages' },
    { id: 'scope_4', name: '/test1/UniqueAG/Freigegebene%20Dokumente' },
    { id: 'scope_5', name: '/test1/UniqueAG/Freigegebene%20Dokumente/General' },
  ];

  const mockScopePathToIdMap: ScopePathToIdMap = {
    '/test1': 'scope_1',
    '/test1/UniqueAG': 'scope_2',
    '/test1/UniqueAG/SitePages': 'scope_3',
    '/test1/UniqueAG/Freigegebene Dokumente': 'scope_4',
    '/test1/UniqueAG/Freigegebene Dokumente/General': 'scope_5',
  };

  let service: ScopeManagementService;
  let configGetMock: ReturnType<typeof vi.fn>;
  let createScopesMock: ReturnType<typeof vi.fn>;
  let getTokenMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    configGetMock = vi.fn((key: string) => {
      if (key === 'unique.rootScopeName') {
        return 'test1';
      }
      return undefined;
    });

    createScopesMock = vi.fn().mockResolvedValue(mockScopes);
    getTokenMock = vi.fn().mockResolvedValue('mock-token');

    const { unit } = await TestBed.solitary(ScopeManagementService)
      .mock<ConfigService>(ConfigService)
      .impl((stubFn) => ({
        ...stubFn(),
        get: configGetMock,
      }))
      .mock<UniqueApiService>(UniqueApiService)
      .impl((stubFn) => ({
        ...stubFn(),
        createScopesBasedOnPaths: createScopesMock,
      }))
      .mock<UniqueAuthService>(UniqueAuthService)
      .impl((stubFn) => ({
        ...stubFn(),
        getToken: getTokenMock,
      }))
      .compile();

    service = unit;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('extractAllParentPaths', () => {
    it('generates hierarchical paths for a single entry', () => {
      const result = service.extractAllParentPaths(['test1/UniqueAG/SitePages']);

      expect(result).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
      expect(new Set(result).size).toBe(result.length);
    });

    it('combines parents for multiple entries', () => {
      const result = service.extractAllParentPaths([
        'test1/UniqueAG/SitePages',
        'test1/UniqueAG/Freigegebene Dokumente/General',
      ]);

      expect(result).toEqual(
        expect.arrayContaining([
          '/test1/UniqueAG/Freigegebene Dokumente',
          '/test1/UniqueAG/Freigegebene Dokumente/General',
        ]),
      );
      expect(result).toContain('/test1/UniqueAG/SitePages');
    });

    it('returns empty array when no paths provided', () => {
      const result = service.extractAllParentPaths([]);
      expect(result).toHaveLength(0);
    });

    it('trims and normalizes paths with trailing slash', () => {
      const result = service.extractAllParentPaths(['test1/UniqueAG/SitePages/']);

      expect(result).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
    });
  });

  describe('batchCreateScopes', () => {
    it('creates scopes and returns decoded scope map', async () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];

      const result = await service.batchCreateScopes(items);

      expect(result.scopes).toEqual(mockScopes);
      expect(result.scopePathToIdMap['/test1/UniqueAG/SitePages']).toBe('scope_3');
      expect(result.scopePathToIdMap['/test1/UniqueAG/Freigegebene Dokumente']).toBe('scope_4');

      const [paths, token] = createScopesMock.mock.calls[0] as [string[], string];
      expect(token).toBe('mock-token');
      expect(paths).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
      expect(getTokenMock).toHaveBeenCalledTimes(1);
    });

    it('returns empty result when no items provided', async () => {
      const result = await service.batchCreateScopes([]);

      expect(result.scopes).toHaveLength(0);
      expect(result.scopePathToIdMap).toEqual({});
      expect(createScopesMock).not.toHaveBeenCalled();
    });

    it('logs site identifier in success message', async () => {
      const logSpy = vi.spyOn(service['logger'], 'log');

      await service.batchCreateScopes([createDriveContentItem('UniqueAG/SitePages')]);

      expect(logSpy).toHaveBeenCalledWith(expect.stringContaining('[SiteId: site-123]'));
    });
  });

  describe('buildItemIdToScopeIdMap', () => {
    it('maps item identifiers to scope identifiers', () => {
      const item = createDriveContentItem('UniqueAG/SitePages');
      const itemIdToScopePathMap = new Map([[item.item.id, '/test1/UniqueAG/SitePages']]);

      const result = service.buildItemIdToScopeIdMap(itemIdToScopePathMap, mockScopePathToIdMap);

      expect(result.get(item.item.id)).toBe('scope_3');
    });

    it('decodes URL-encoded paths before lookup', () => {
      const item = createDriveContentItem('UniqueAG/Freigegebene%20Dokumente/General');
      const itemIdToScopePathMap = new Map([
        [item.item.id, '/test1/UniqueAG/Freigegebene Dokumente/General'],
      ]);

      const result = service.buildItemIdToScopeIdMap(itemIdToScopePathMap, mockScopePathToIdMap);

      expect(result.get(item.item.id)).toBe('scope_5');
    });

    it('returns empty map when scope map is undefined', () => {
      const item = createDriveContentItem('UniqueAG/SitePages');
      const itemIdToScopePathMap = new Map([[item.item.id, '/test1/UniqueAG/SitePages']]);

      const result = service.buildItemIdToScopeIdMap(itemIdToScopePathMap, undefined);

      expect(result.size).toBe(0);
    });

    it('logs warning when scope is not present in cache', () => {
      const warnSpy = vi.spyOn(service['logger'], 'warn');
      const item = createDriveContentItem('UniqueAG/UnknownFolder');
      const itemIdToScopePathMap = new Map([[item.item.id, '/test1/UniqueAG/UnknownFolder']]);

      service.buildItemIdToScopeIdMap(itemIdToScopePathMap, mockScopePathToIdMap);

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('/test1/UniqueAG/UnknownFolder'),
      );
    });
  });
});
