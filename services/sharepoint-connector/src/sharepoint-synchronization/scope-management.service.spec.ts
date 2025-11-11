import { ConfigService } from '@nestjs/config';
import { TestBed } from '@suites/unit';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SharepointContentItem } from '../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueScopesService } from '../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { ScopeManagementService } from './scope-management.service';

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
    { id: 'scope_1', name: 'test1', parentId: null },
    {
      id: 'scope_2',
      name: 'UniqueAG',
      parentId: 'scope_1',
    },
    {
      id: 'scope_3',
      name: 'SitePages',
      parentId: 'scope_2',
    },
    {
      id: 'scope_4',
      name: 'Freigegebene Dokumente',
      parentId: 'scope_2',
    },
    {
      id: 'scope_5',
      name: 'General',
      parentId: 'scope_4',
    },
  ];

  let service: ScopeManagementService;
  let configGetMock: ReturnType<typeof vi.fn>;
  let createScopesMock: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    configGetMock = vi.fn((key: string) => {
      if (key === 'unique.rootScopeName') {
        return 'test1';
      }
      return undefined;
    });

    createScopesMock = vi.fn().mockResolvedValue(
      mockScopes.map(({ id, name, parentId, scopeAccess }) => ({
        id,
        name,
        parentId,
        scopeAccess,
      })),
    );

    const { unit } = await TestBed.solitary(ScopeManagementService)
      .mock<ConfigService>(ConfigService)
      .impl((stubFn) => ({
        ...stubFn(),
        get: configGetMock,
      }))
      .mock<UniqueScopesService>(UniqueScopesService)
      .impl((stubFn) => ({
        ...stubFn(),
        createScopesBasedOnPaths: createScopesMock,
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
    it('creates scopes and returns list', async () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];

      const result = await service.batchCreateScopes(items);

      expect(result).toEqual(
        expect.arrayContaining(mockScopes.map((scope) => expect.objectContaining(scope))),
      );

      const [paths, options] = createScopesMock.mock.calls[0] as [
        string[],
        { includePermissions: boolean },
      ];
      expect(options).toEqual({ includePermissions: true });
      expect(paths).toEqual(
        expect.arrayContaining(['/test1', '/test1/UniqueAG', '/test1/UniqueAG/SitePages']),
      );
    });

    it('returns empty list when no items provided', async () => {
      const result = await service.batchCreateScopes([]);

      expect(result).toHaveLength(0);
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
      const items = [createDriveContentItem('UniqueAG/SitePages')];
      const item = items[0]!;

      const result = service.buildItemIdToScopeIdMap(items, mockScopes);

      expect(result.get(item.item.id)).toBe('scope_3');
    });

    it('decodes URL-encoded paths before lookup', () => {
      const items = [createDriveContentItem('UniqueAG/Freigegebene%20Dokumente/General')];
      const item = items[0]!;

      const result = service.buildItemIdToScopeIdMap(items, mockScopes);

      expect(result.get(item.item.id)).toBe('scope_5');
    });

    it('returns empty map when scopes is empty', () => {
      const items = [createDriveContentItem('UniqueAG/SitePages')];

      const result = service.buildItemIdToScopeIdMap(items, []);

      expect(result.size).toBe(0);
    });

    it('logs warning when scope is not present in cache', () => {
      const warnSpy = vi.spyOn(service['logger'], 'warn');
      const items = [createDriveContentItem('UniqueAG/UnknownFolder')];

      service.buildItemIdToScopeIdMap(items, mockScopes);

      expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining('UnknownFolder'));
    });
  });
});
